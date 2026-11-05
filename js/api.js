// Data access. Two backends behind one interface:
//   local  — same-origin files, used by `python -m http.server` during development.
//   github — Git Data API against the private repo's dashboard-data branch, authenticated
//            with a read-only fine-grained PAT that lives only in this browser.
//
// Blobs are addressed by SHA, which is immutable: the same SHA is the same bytes forever,
// so a page reload only ever re-reads the tree and the manifest.

const TOKEN_KEY = "jobdash.pat";
const PREF_KEY = "jobdash.prefs";

// Overridable through prefs so the private-data fetch path can be exercised against a
// local API stub without spending a real token (see tests/support/github_api_stub.py).
// An empty string means "same origin as the page", which is how the stub is served.
const API = (() => {
  try {
    const prefs = JSON.parse(localStorage.getItem(PREF_KEY) || "{}");
    return typeof prefs.apiBase === "string" ? prefs.apiBase : "https://api.github.com";
  } catch {
    return "https://api.github.com";
  }
})();

const SNAPSHOT_DIR = "snapshot";

export class AuthError extends Error {}
export class RateLimitError extends Error {}

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token.trim());
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export function getPrefs() {
  try {
    return JSON.parse(localStorage.getItem(PREF_KEY) || "{}");
  } catch {
    return {};
  }
}

export function setPref(key, value) {
  const prefs = getPrefs();
  if (value === undefined) delete prefs[key];
  else prefs[key] = value;
  localStorage.setItem(PREF_KEY, JSON.stringify(prefs));
}

export function defaultRepo() {
  const prefs = getPrefs();
  return { owner: prefs.owner || "xiejiongru", repo: prefs.repo || "job_pipeline", ref: prefs.ref || "dashboard-data" };
}

async function request(path, { token = "", accept = "application/vnd.github+json", raw = false } = {}) {
  const headers = { Accept: accept, "X-GitHub-Api-Version": "2022-11-28" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path.startsWith("http") ? path : `${API}${path}`, { headers });

  if (response.status === 401) throw new AuthError("Token 无效、已过期或已被撤销。");
  if (response.status === 403 || response.status === 429) {
    const remaining = response.headers.get("x-ratelimit-remaining");
    const reset = response.headers.get("x-ratelimit-reset");
    if (remaining === "0" && reset) {
      const minutes = Math.max(0, Math.round((Number(reset) * 1000 - Date.now()) / 60000));
      throw new RateLimitError(`GitHub API 限流，约 ${minutes} 分钟后恢复。`);
    }
    throw new AuthError("Token 有效但没有该仓库 Contents: read-only 权限，或访问被 GitHub 拦截。");
  }
  if (response.status === 404) throw new Error(`找不到 ${path}`);
  if (!response.ok) throw new Error(`GitHub API ${response.status}：${path}`);
  return raw ? response : response.json();
}

async function gunzip(buffer) {
  if (!("DecompressionStream" in window)) {
    throw new Error("此浏览器不支持 DecompressionStream（需要 Chrome/Edge 80+、Firefox 113+、Safari 16.4+）。");
  }
  const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).text();
}

export function createLocalBackend(basePath = SNAPSHOT_DIR) {
  const base = new URL(basePath, document.baseURI).href;
  return {
    kind: "local",
    async manifest() {
      const response = await fetch(`${base}/manifest.json`, { cache: "no-store" });
      if (!response.ok) throw new Error(`本地快照缺失：manifest.json (${response.status})`);
      return response.json();
    },
    async file(name) {
      const response = await fetch(`${base}/${name}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`本地快照缺失：${name} (${response.status})`);
      if (name.endsWith(".gz")) return gunzip(await response.arrayBuffer());
      return response.text();
    },
    async refs() {
      return [{ label: "local", title: "本地目录快照" }];
    },
  };
}

export function createGithubBackend({ owner, repo, ref, token }) {
  if (!token) throw new AuthError("尚未输入访问令牌。");
  const blobCache = new Map();
  let treePromise = null;

  const loadTree = (which) => {
    if (!treePromise) {
      treePromise = request(`/repos/${owner}/${repo}/git/trees/${encodeURIComponent(which)}?recursive=1`, {
        token,
      })
        .then((tree) => {
          const byPath = new Map();
          for (const entry of tree.tree || []) if (entry.type === "blob") byPath.set(entry.path, entry);
          return byPath;
        })
        .catch((error) => {
          treePromise = null;
          throw error;
        });
    }
    return treePromise;
  };

  return {
    kind: "github",
    async manifest() {
      const entry = await this.blob(SNAPSHOT_DIR + "/manifest.json");
      return JSON.parse(await textOf(entry));
    },
    async blob(path) {
      const tree = await loadTree(ref);
      const entry = tree.get(path);
      if (!entry) throw new Error(`分支 ${ref} 里没有 ${path}。可能还没发布过快照。`);
      return entry;
    },
    async file(name) {
      const entry = await this.blob(`${SNAPSHOT_DIR}/${name}`);
      return textOf(entry);
    },
    async refs() {
      const commits = await request(
        `/repos/${owner}/${repo}/commits?sha=${encodeURIComponent(ref)}&path=${SNAPSHOT_DIR}&per_page=30`,
        { token },
      );
      return (commits || []).map((commit) => ({
        label: commit.sha.slice(0, 10),
        title: `${(commit.commit.author && commit.commit.author.date) || ""} · ${commit.commit.message.split("\n")[0]}`,
      }));
    },
  };

  async function textOf(entry) {
    if (blobCache.has(entry.sha)) return blobCache.get(entry.sha);
    const response = await request(`/repos/${owner}/${repo}/git/blobs/${entry.sha}`, {
      token,
      accept: "application/vnd.github.raw+json",
      raw: true,
    });
    const buffer = await response.arrayBuffer();
    const text = entry.path.endsWith(".gz") ? await gunzip(buffer) : await new Response(buffer).text();
    blobCache.set(entry.sha, text);
    return text;
  }
}

export async function loadDataset(backend) {
  const manifest = await backend.manifest();
  const [indexText, runsText] = await Promise.all([
    backend.file(fileName(manifest, "index_file")),
    backend.file(fileName(manifest, "runs_file")),
  ]);
  const index = JSON.parse(indexText);
  const runs = JSON.parse(runsText);
  return { manifest, columns: index.columns || manifest.index_columns || [], rows: index.rows || [], runs };
}

export async function loadDescriptions(backend, manifest) {
  return JSON.parse(await backend.file(fileName(manifest, "details_file")));
}

function fileName(manifest, key) {
  const fallbacks = { index_file: "index.json.gz", runs_file: "runs.json.gz", details_file: "descriptions.json.gz" };
  const name = manifest[key] || fallbacks[key];
  if (!name) throw new Error(`manifest 里没有 ${key}`);
  return name;
}
