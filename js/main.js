// Dashboard shell. Views are rendered from the loaded snapshot only; the network layer
// lives in api.js and the row model in data.js.

import {
  AuthError,
  RateLimitError,
  clearToken,
  createGithubBackend,
  createLocalBackend,
  defaultRepo,
  getToken,
  getPrefs,
  loadDataset,
  loadDescriptions,
  setPref,
  setToken,
} from "./api.js";
import { createDataset, filterRows, sortRows, statsFor } from "./data.js";
import { barChart, histogram, lineChart, toOrdinal } from "./charts.js";
import { download, stamp, toCsv } from "./csv.js";
import { STATUSES, createOverlay, createVisited } from "./overlay.js";
import { TIERS } from "./tiers.js";

const VIEWS = ["overview", "explorer", "history", "settings"];

// The table shows what you scan by; everything else (country, remote, first/last seen,
// per-dimension scores, ...) lives in the detail panel and the CSV export, which still
// carries every column. `sort` is the row field a header click sorts by.
const TABLE_HEAD = [
  { key: "link", label: "↗", title: "打开原招聘页（新标签页）" },
  { key: "check", label: "" },
  { key: "score", label: "评分 / 档位", sort: "priority", title: "默认按「档位 + 分数」排序：先是通过闸门的高分岗位，被拦截和已关闭的沉底" },
  { key: "title", label: "职位", sort: "title" },
  { key: "company", label: "公司", sort: "company" },
  { key: "location", label: "地点", sort: "city" },
  { key: "salary", label: "薪资", sort: "salary_gross_min" },
  { key: "employment_type", label: "合同", sort: "employment_type" },
  { key: "published_at", label: "发布", sort: "published_at" },
  { key: "source", label: "来源", sort: "source" },
  { key: "status", label: "招聘", sort: "status" },
  { key: "visa_status", label: "签证担保", title: "岗位自己的话：担保✓=写明提供签证担保，无担保✕=明确不提供，担保?=没提（未知不等于可以）" },
  { key: "mine", label: "我的状态", title: "只存本机浏览器" },
];
const SORT_CHOICES = [
  ["priority", "推荐（档位 + 分数）"],
  ["final_score", "纯分数"],
  ["published_at", "发布时间"],
  ["first_seen_at", "首次出现"],
];
// Application stages that deserve a visible marker on the row.
const STAGE_CLASS = { 已投递: "st-live", 已回复: "st-live", 面试中: "st-live", Offer: "st-live", 拒绝: "st-dead", 放弃: "st-dead", 已关闭: "st-dead" };
const DETAIL_GROUPS = [
  // The snapshot's link column is `url`; `canonical_url` is not in it, so listing that
  // here showed "—" for every job.
  ["职位身份", ["job_id", "source", "source_job_id", "url", "status", "content_hash", "schema_version"]],
  ["基本信息", ["title", "company", "location", "country", "employment_type", "remote", "salary", "salary_gross_min", "salary_gross_max", "salary_basis", "published_at"]],
  ["时间线", ["discovered_at", "first_seen_at", "last_seen_at", "missed_runs", "closed_at"]],
  ["程序评分", ["final_score", "decision", "screening_score", "seniority", "score_tech_match", "score_function_match", "score_domain_match", "score_experience_match", "score_growth_potential", "rules_version", "model_version", "kernel_version"]],
  ["判定与依据", ["hard_filter_passed", "hard_filter_reasons", "filter_reasons", "missing_skills", "risk_factors", "leverage_points", "summary", "thinking_trace", "normalization_warnings"]],
  ["技能抽取", ["gis_skills", "data_skills", "devops_skills", "programming_skills"]],
];

const state = {
  backend: null,
  manifest: null,
  columns: [],
  rows: [],
  runs: [],
  dataset: null,
  descriptions: null,
  overlay: createOverlay(),
  visited: createVisited(),
  query: freshQuery({ hideClosed: getPrefs().hideClosed === true, hideVisited: getPrefs().hideVisited === true }),
  sort: { column: "priority", direction: "desc" },
  sortChain: [],
  lastFocus: null,
  skipOverlayRender: false,
  page: 0,
  pageSize: 50,
  selected: new Set(),
  activeJob: "",
  legacyOnly: getPrefs().legacyOnly === true,
  density: getPrefs().density || "standard",
  visibleCols: getPrefs().visibleCols || ["title", "company", "location", "score", "salary", "published_at"],
  colsConfigOpen: false,
  view: "overview",
  loading: false,
  error: "",
};

const els = {};

function h(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value === null || value === undefined) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.appendChild(typeof child === "string" || typeof child === "number" ? document.createTextNode(String(child)) : child);
  }
  return node;
}

function clear(node) {
  node.replaceChildren();
  return node;
}

function shortDate(value) {
  const text = String(value || "").slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return text || "—";
  const [y, m, d] = text.split("-");
  const months = ["jan", "fév", "mar", "avr", "mai", "juin", "juil", "août", "sep", "oct", "nov", "déc"];
  return `${Number(d)} ${months[Number(m) - 1]} ${y}`;
}

function pretty(name) {
  return name.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function cellText(row, column) {
  const value = row[column];
  return value === undefined || value === null ? "" : String(value);
}

function freshQuery(overrides = {}) {
  return {
    text: "",
    facets: {},
    scoreRange: [null, null],
    dateRange: { start: "", end: "" },
    statuses: [],
    searchJd: false,
    tiers: [],
    hideClosed: false,
    hideVisited: false,
    ...overrides,
  };
}

// Only ever hand http(s) URLs to an href: the data is ours, but a javascript: URL in a
// scraped field would otherwise become a click-to-run link.
function safeUrl(value) {
  const text = String(value || "").trim();
  return /^https?:\/\//i.test(text) ? text : "";
}

function hostOf(href) {
  try {
    return new URL(href).hostname.replace(/^www\./, "");
  } catch {
    return href;
  }
}

function tierMeta(id) {
  return TIERS.find((tier) => tier.id === id) || TIERS[TIERS.length - 1];
}

// Opening a posting (via the link icon or its detail panel) marks it as seen. The row is
// updated in place; re-rendering the table here would reset the scroll position.
function markVisited(jobId, rowNode) {
  state.visited.mark(jobId);
  if (rowNode) rowNode.classList.add("is-visited");
}

function externalLink(row, { rowNode = null, text = "↗", className = "ext" } = {}) {
  const href = safeUrl(row.url) || safeUrl(row.canonical_url);
  if (!href) return null;
  const onOpen = () => markVisited(row.job_id, rowNode);
  return h("a", {
    class: className,
    href,
    target: "_blank",
    rel: "noopener noreferrer",
    title: `打开原招聘页 · ${hostOf(href)}`,
    "aria-label": `打开原招聘页：${row.title || ""}`,
    onclick: onOpen,
    // Middle-click opens a tab without a click event.
    onauxclick: (event) => {
      if (event.button === 1) onOpen();
    },
    text,
  });
}

// ---------------------------------------------------------------- boot

export function boot() {
  // GitHub Pages cannot send response headers, so frame-ancestors is unreachable from a
  // meta tag. This is the static fallback for the same intent: never render inside someone
  // else's frame while the user is about to paste a token.
  if (window.top !== window.self) {
    document.body.replaceChildren();
    document.body.appendChild(h("p", { text: "为避免套壳钓鱼，本页面拒绝在 iframe 中渲染。请直接访问站点地址。" }));
    return;
  }
  for (const id of ["auth", "app", "status", "tabs", "view", "snapinfo", "token", "owner", "repo", "ref", "errbox"]) {
    els[id] = document.getElementById(id);
  }
  const params = new URLSearchParams(location.search);
  const localMode = params.get("mode") === "local";

  bindAuth(localMode);
  readUrlState();
  setupKeyboardNav();
  applyDensity();
  bindTabs();
  state.overlay.onChange(() => {
    if (state.skipOverlayRender) return;
    if (state.view === "explorer") renderExplorer();
  });
  window.addEventListener("jobdash:error", (event) => showError(event.detail));

  if (localMode) {
    startSession(createLocalBackend(params.get("snapshot") || "snapshot"), "本地目录模式");
    return;
  }
  showAuth();
}

function bindAuth(localMode) {
  const prefs = getPrefs();
  els.owner.value = prefs.owner || "xiejiongru";
  els.repo.value = prefs.repo || "job_pipeline";
  els.ref.value = prefs.ref || "dashboard-data";
  els.token.value = getToken();
  document.getElementById("auth-note").hidden = !localMode;

  document.getElementById("auth-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const token = els.token.value.trim();
    if (!token) {
      showError("访问令牌不能为空。它只需 job_pipeline 的 Contents: read-only。");
      return;
    }
    setToken(token);
    for (const key of ["owner", "repo", "ref"]) setPref(key, els[key].value.trim());
    const repo = { owner: els.owner.value.trim(), repo: els.repo.value.trim(), ref: els.ref.value.trim() };
    startSession(createGithubBackend({ ...repo, token: els.token.value.trim() }), `${repo.owner}/${repo.repo}@${repo.ref}`);
  });

  document.getElementById("forget-token").addEventListener("click", () => {
    els.token.value = "";
    document.getElementById("token-box").hidden = true;
  });

  document.getElementById("logout").addEventListener("click", () => {
    clearToken();
    els.token.value = "";
    state.backend = null;
    els.app.hidden = true;
    showAuth("已清除本机令牌。");
  });
}

function showAuth(message) {
  els.auth.hidden = false;
  els.app.hidden = true;
  if (message) setStatus(message);
  document.getElementById("token-box").hidden = !getToken();
  els.token.value = getToken();
}

async function startSession(backend, label) {
  els.auth.hidden = true;
  els.app.hidden = false;
  els.token.value = "";
  setStatus(`正在读取 ${label} 的快照…`);
  renderSkeleton();
  state.backend = backend;
  await reload();
}

async function reload() {
  if (!state.backend || state.loading) return;
  state.loading = true;
  state.error = "";
  clear(els.errbox);
  try {
    const dataset = await loadDataset(state.backend);
    state.manifest = dataset.manifest;
    state.columns = dataset.columns;
    state.runs = dataset.runs;
    state.dataset = createDataset(dataset.rows);
    // The derived rows are the only representation: they carry city/posted_day, which
    // the date filter and the stat cards read. Using the raw rows here silently zeroed
    // both, because a raw row has no posted_day.
    state.rows = state.dataset.rows;
    state.descriptions = null;
    render();
    setStatus(snapshotLine(labelFromManifest(dataset.manifest)));
  } catch (error) {
    state.error = error.message || String(error);
    if (error instanceof AuthError || error instanceof RateLimitError) {
      showError(error.message);
    } else {
      showError(`${error.message}（若分支 ${defaultRepo().ref} 尚未发布过快照，先跑一次爬虫工作流）`);
    }
    if (!getToken() && !(state.backend && state.backend.kind === "local")) showAuth();
  } finally {
    state.loading = false;
  }
}

function labelFromManifest(manifest) {
  const source = manifest.source || {};
  const stamp = manifest.latest_run_completed_at || "未知轮次";
  return `${manifest.jobs_rows} 条岗位 · 数据截至 ${stamp}${source.commit ? ` · 构建 ${source.commit}` : ""}`;
}

function setStatus(text) {
  els.status.textContent = text;
}

function showError(text) {
  clear(els.errbox);
  els.errbox.hidden = false;
  els.errbox.appendChild(h("div", { class: "error-box" }, text));
  if (text.includes("快照分支")) {
    els.errbox.appendChild(h("p", { class: "muted" }, "下一步：运行一次爬虫工作流（scraper-cron.yml），它会发布 snapshot 到 dashboard-data 分支。"));
  } else if (text.includes("令牌") || text.includes("401") || text.includes("403")) {
    els.errbox.appendChild(h("p", { class: "muted" }, "下一步：检查 PAT 是否过期，或重新生成一把只读 token。"));
  }
}

function snapshotLine(label) {
  const runs = state.runs.length ? state.runs[0].completed_at : "无";
  return `${label} · 最近一轮 ${runs} · 历史 ${state.runs.length} 轮`;
}

function bindTabs() {
  clear(els.tabs);
  for (const view of VIEWS) {
    els.tabs.appendChild(
      h("button", {
        type: "button",
        class: `tab${state.view === view ? " is-active" : ""}`,
        "data-view": view,
        onclick: () => {
          state.view = view;
          bindTabs();
          render();
        },
      }, tabLabel(view))
    );
  }
}

function tabLabel(view) {
  return { overview: "总览", explorer: "职位浏览器", history: "爬取历史", settings: "数据与隐私" }[view];
}

// ---------------------------------------------------------------- render

function pushUrlState() {
  try {
    const params = new URLSearchParams();
    if (state.view && state.view !== "overview") params.set("view", state.view);
    if (state.activeJob) params.set("job", state.activeJob);
    if (state.query.text) params.set("q", state.query.text);
    if (state.query.tiers && state.query.tiers.length) params.set("tiers", state.query.tiers.join(","));
    if (state.hideClosed) params.set("hideClosed", "1");
    if (state.hideVisited) params.set("hideVisited", "1");
    if (state.sort && state.sort.column) {
      const keys = activeSortKeys();
      params.set("sort", keys.map((key) => key.column).join(","));
      params.set("dir", keys.map((key) => key.direction).join(","));
    }
    if (state.page) params.set("page", String(state.page));
    const qs = params.toString();
    const url = qs ? `${location.pathname}?${qs}` : location.pathname;
    history.replaceState(null, "", url);
  } catch { /* ignore URL API failures */ }
}

function readUrlState() {
  try {
    const params = new URLSearchParams(location.search);
    if (params.has("view")) state.view = params.get("view");
    if (params.has("job")) state.activeJob = params.get("job");
    if (params.has("q")) state.query.text = params.get("q");
    if (params.has("tiers")) state.query.tiers = params.get("tiers").split(",").filter(Boolean);
    if (params.has("hideClosed")) state.query.hideClosed = true;
    if (params.has("hideVisited")) state.query.hideVisited = true;
    if (params.has("sort")) {
      const columns = (params.get("sort") || "").split(",").filter(Boolean);
      const dirs = (params.get("dir") || "").split(",");
      if (columns.length) {
        state.sort = { column: columns[0], direction: dirs[0] === "asc" ? "asc" : "desc" };
        state.sortChain = columns.slice(1).map((column, index) => ({
          column,
          direction: dirs[index + 1] === "asc" ? "asc" : "desc",
        }));
      }
    }
    if (params.has("page")) state.page = Number(params.get("page")) || 0;
  } catch { /* ignore */ }
}

function setupKeyboardNav() {
  document.addEventListener("keydown", (event) => {
    // Escape closes the drawer even when the caret is inside its note field: otherwise the
    // one key everybody tries first does nothing while you are editing.
    if (event.key === "Escape") {
      const drawer = document.getElementById("drawer");
      if (drawer && drawer.classList.contains("open")) {
        event.preventDefault();
        closeJob();
      }
      return;
    }
    if (event.target && (event.target.tagName === "INPUT" || event.target.tagName === "TEXTAREA" || event.target.tagName === "SELECT")) return;
    if (state.view !== "explorer") return;
    const rows = filteredRows();
    if (!rows.length) return;
    const idx = rows.findIndex((r) => r.job_id === state.activeJob);
    if (event.key === "j" || event.key === "ArrowDown") {
      event.preventDefault();
      const next = Math.min(rows.length - 1, idx < 0 ? 0 : idx + 1);
      openJob(rows[next].job_id);
    } else if (event.key === "k" || event.key === "ArrowUp") {
      event.preventDefault();
      const prev = Math.max(0, idx < 0 ? 0 : idx - 1);
      openJob(rows[prev].job_id);
    } else if (event.key === "Enter" && idx >= 0) {
      event.preventDefault();
      const url = rows[idx].url;
      if (url) window.open(url, "_blank", "noopener");
    } else if (event.key === "x" && idx >= 0) {
      event.preventDefault();
      state.overlay.set(rows[idx].job_id, { status: "\u5df2\u6295\u9012" });
      const tr = document.querySelector('tr[data-job="' + rows[idx].job_id + '"]');
      if (tr) tr.className = rowClass(rows[idx]);
    } else if (event.key === "e" && idx >= 0) {
      event.preventDefault();
      const id = rows[idx].job_id;
      const note = prompt("\u5907\u6ce8\uff1a", state.overlay.get(id).notes || "");
      if (note !== null) state.overlay.set(id, { notes: note });
    } else if (event.key === "v" && idx >= 0) {
      event.preventDefault();
      const url = rows[idx].url;
      if (url) window.open(url, "_blank", "noopener");
    }
  });
}


function applyDensity() {
  document.body.classList.remove("density-compact", "density-standard", "density-loose");
  document.body.classList.add("density-" + (state.density || "standard"));
  setPref("density", state.density);
}

function render() {
  clear(els.view);
  if (!state.manifest) {
    renderSkeleton();
    return;
  }
  els.snapinfo.textContent = labelFromManifest(state.manifest);
  if (state.view === "overview") renderOverview();
  else if (state.view === "explorer") renderExplorer();
  else if (state.view === "history") renderHistory();
  else renderSettings();
}

// The snapshot is gzip and carries thousands of rows; a cold load used to show one grey
// line above an empty page, which reads as "broken". A skeleton says the layout is coming.
// Widths are classes, not inline styles: CSP `style-src 'self'` forbids the style attribute.
function renderSkeleton() {
  if (state.manifest) return;
  const rows = [0, 1, 2, 3, 4, 5, 6, 7].map(() =>
    h("div", { class: "skeleton-row" }, [
      h("span", { class: "skeleton sk-link" }),
      h("span", { class: "skeleton sk-check" }),
      h("span", { class: "skeleton sk-title" }),
      h("span", { class: "skeleton sk-company" }),
      h("span", { class: "skeleton sk-meta" }),
    ])
  );
  clear(els.view);
  els.view.appendChild(h("div", { class: "card", "aria-busy": "true", "aria-label": "正在读取快照" }, [
    h("div", { class: "skeleton skeleton-heading" }),
    ...rows,
  ]));
}

function section(title, children = [], attrs = {}) {
  return h("section", { class: "card" }, [h("h2", attrs, title), ...[].concat(children)]);
}

function kpiGrid(items) {
  return h(
    "div",
    { class: "kpis" },
    items.map(([label, value, hint]) => h("div", { class: "kpi" }, [h("span", { class: "kpi-value", text: String(value) }), h("span", { class: "kpi-label", text: label }), hint ? h("span", { class: "kpi-hint", text: hint }) : null]))
  );
}

// ----------------------------------------------------------- overview

function renderTodoSection() {
  const base = baseRows();
  const newDay = state.runs[0] && state.runs[0].completed_at ? String(state.runs[0].completed_at).slice(0, 10) : "";
  const newRows = newDay ? base.filter((row) => row.first_seen_day === newDay) : [];
  const unseenApply = base.filter((row) => row.decision === "apply" && !state.visited.has(row.job_id) && row.status !== "closed");
  const topUnseen = unseenApply.slice(0, 8);
  return h("section", { class: "card todo-section" }, [
    h("h2", {}, "今日 / 待办"),
    h("div", { class: "kpis" }, [
      h("div", { class: "kpi" }, [h("div", { class: "kpi-value", text: String(newRows.length) }), h("div", { class: "kpi-label", text: "本轮新增" })]),
      h("div", { class: "kpi" }, [h("div", { class: "kpi-value", text: String(unseenApply.length) }), h("div", { class: "kpi-label", text: "未查看且 apply" })]),
      h("div", { class: "kpi" }, [h("div", { class: "kpi-value", text: String(base.filter((r) => r.decision === "apply").length) }), h("div", { class: "kpi-label", text: "apply 总数" })]),
    ]),
    h("h3", {}, "未查看且 apply 的职位"),
    topUnseen.length ? h("ul", { class: "linklist" }, topUnseen.map((row) =>
      h("li", {}, [
        h("a", { href: "#", onclick: (e) => { e.preventDefault(); openJob(row.job_id); }, text: row.title }),
        h("span", { class: "muted", text: " · " + (row.company || "") + " · " + (row.final_score || "—") + " 分" }),
      ])
    )) : h("p", { class: "muted" }, "没有未查看的 apply 职位。"),
  ]);
}

function renderOverview() {
  const rows = state.rows;
  const stats = statsFor(rows);
  const latest = state.runs[0] || {};
  const seenDay = latest.completed_at ? String(latest.completed_at).slice(0, 10) : "";
  const newThisRun = rows.filter((row) => seenDay && String(row.first_seen_at || "").slice(0, 10) === seenDay).length;

  clear(els.view);
  els.view.appendChild(renderTodoSection());
  els.view.appendChild(
    section("市场总览", [
      kpiGrid([
        ["累计职位", stats.total, `${stats.companies} 家公司 / ${stats.countries} 个国家`],
        ["最近一轮新增", latest.new_records ?? newThisRun, seenDay ? `首轮出现于 ${seenDay}` : "无历史轮次"],
        ["判定可投 apply", stats.apply, `待定 ${stats.needs_review} · 拦截 ${stats.skip}`],
        ["中位评分", stats.median_score ?? "—", `${stats.scored} 条已评分`],
        ["有薪资数值", stats.with_salary_numeric, stats.with_salary ? `字段 ${stats.basis_field} · 正文解析 ${stats.basis_text}` : "本轮没有可读的薪资数字"],
        ["有发布日期", stats.with_published_at, stats.oldest ? `${stats.oldest} → ${stats.newest}` : "全部缺日期"],
      ]),
    ])
  );

  els.view.appendChild(
    h("div", { class: "grid-2" }, [
      section("按国家", barChart(state.dataset.facets.country.filter(([k]) => k !== "(空)").slice(0, 10))),
      section("按城市 Top 10", barChart(state.dataset.facets.city.filter(([k]) => k !== "(空)").slice(0, 10))),
      section("按公司 Top 10", barChart(state.dataset.facets.company.filter(([k]) => k !== "(空)").slice(0, 10))),
      section("按数据来源", barChart(state.dataset.facets.source.slice(0, 12))),
      section("按合同类型", barChart(state.dataset.facets.employment_type)),
      section("按经验层级", barChart(state.dataset.facets.seniority)),
    ])
  );

  els.view.appendChild(
    h("div", { class: "grid-2" }, [
      section("评分分布", histogram(rows.map((row) => row.final_score).filter((v) => v !== ""), { title: "final_score", bins: 12 })),
      salarySection(rows),
    ])
  );

  els.view.appendChild(section("趋势", [trendChart()], { class: "card" }));
  els.view.appendChild(
    h("div", { class: "grid-2" }, [
      section("最近发布的职位", listBlock(mostRecent(rows), (row) => `${row.title} · ${row.company} · ${row.published_at || "无日期"}`)),
      section("与目标最匹配的职位", listBlock(bestMatches(rows), (row) => `${row.title} · ${row.company} · ${row.final_score} 分`)),
    ])
  );
}

function salarySection(rows) {
  const numeric = rows.filter((row) => row.salary_gross_min !== "" && Number(row.salary_gross_min) > 0);
  const raw = rows.filter((row) => String(row.salary || "").trim());
  if (!numeric.length) {
    if (!raw.length) {
      return section("薪资分布", [h("p", { class: "muted" }, `${rows.length} 条职位里 0 条带可读的欧元薪资。爬虫不编造薪资，所以这里没有图。`)]);
    }
    const counts = new Map();
    for (const row of raw) counts.set(row.salary.trim(), (counts.get(row.salary.trim()) || 0) + 1);
    return section("薪资原文分组（未数值化）", [barChart([...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12))]);
  }
  const basis = { field: 0, text: 0 };
  for (const row of numeric) basis[row.salary_basis] = (basis[row.salary_basis] || 0) + 1;
  const ceilings = numeric.filter((row) => row.salary_gross_max !== "");
  const caption = h("p", { class: "muted" }, [
    `${numeric.length} 条有数值区间：雇主字段直述 ${basis.field} 条，JD 正文解析 ${basis.text} 条。`,
    `图按区间下界统计；${numeric.length - ceilings.length} 条只写了"à partir de"这类下界，无上界。`,
    `正文解析的下限闸门是 5,000 €/年（低于它的一律视为非薪资数字），该闸门只作用于看板，不改过滤逻辑。`,
  ]);
  const rawCounts = new Map();
  for (const row of raw) rawCounts.set(row.salary.trim(), (rawCounts.get(row.salary.trim()) || 0) + 1);
  return section("薪资分布（毛年薪，€）", [
    caption,
    histogram(numeric.map((row) => row.salary_gross_min), { title: "区间下界", bins: 12 }),
    ceilings.length
      ? histogram(ceilings.map((row) => row.salary_gross_max), { title: "区间上界", bins: 12 })
      : h("p", { class: "muted" }, "没有任何条目带可读的上界。"),
    barChart([...rawCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8), { title: "原文写法 Top 8（数值化的输入长什么样）" }),
  ]);
}

function trendChart() {
  const byDay = new Map();
  for (const row of state.rows) {
    const day = String(row.first_seen_at || "").slice(0, 10);
    if (!day) continue;
    byDay.set(day, (byDay.get(day) || 0) + 1);
  }
  const days = [...byDay.keys()].sort();
  let cumulative = 0;
  const totalPoints = [];
  const newPoints = [];
  for (const day of days) {
    cumulative += byDay.get(day);
    const ordinal = toOrdinal(day);
    if (ordinal === null) continue;
    totalPoints.push([ordinal, cumulative]);
    newPoints.push([ordinal, byDay.get(day)]);
  }
  const runPoints = state.runs
    .map((run) => {
      const day = String(run.completed_at || "").slice(0, 10);
      const ordinal = toOrdinal(day);
      return ordinal === null ? null : [ordinal, Number(run.job_records || run.scraped || 0)];
    })
    .filter(Boolean);
  return h("div", { class: "chart-wrap" }, [
    lineChart([{ name: "累计在册职位（按首次见到日）", points: totalPoints }, { name: "每日新增", points: newPoints }], { title: "职位积累趋势", height: 260 }),
    runPoints.length
      ? lineChart([{ name: "每轮 store 总量", points: runPoints }], { title: "每轮运行后的记录总量", height: 220 })
      : h("p", { class: "muted" }, "还没有多轮运行记录。"),
  ]);
}

function mostRecent(rows) {
  return rows
    .filter((row) => row.published_at)
    .slice()
    .sort((a, b) => String(b.published_at).localeCompare(String(a.published_at)))
    .slice(0, 12);
}

function bestMatches(rows) {
  return rows
    .filter((row) => row.decision !== "skip")
    .slice()
    .sort((a, b) => (Number(b.final_score) || 0) - (Number(a.final_score) || 0))
    .slice(0, 12);
}

function listBlock(rows, label) {
  if (!rows.length) return h("p", { class: "muted" }, "无。");
  return h(
    "ul",
    { class: "linklist" },
    rows.map((row) =>
      h("li", {}, [
        h("a", { href: "#", onclick: (event) => { event.preventDefault(); openJob(row.job_id); }, text: label(row) }),
      ])
    )
  );
}

// ----------------------------------------------------------- explorer

// Everything except the tier chips, so each chip can show how many rows it would give
// under the *other* active filters.
function baseRows() {
  return filterRows(state.rows, {
    text: state.query.text,
    facets: state.query.facets,
    scoreRange: state.query.scoreRange,
    dateRange: state.query.dateRange,
    overlayStatuses: state.query.statuses,
    getOverlay: (id) => state.overlay.get(id),
    searchJd: state.query.searchJd,
    descriptions: state.query.searchJd ? state.descriptions : null,
    hideClosed: state.query.hideClosed,
    hideVisited: state.query.hideVisited,
    isVisited: (id) => state.visited.has(id),
  });
}

function filteredRows(base = baseRows()) {
  const picked = state.query.tiers;
  const rows = picked.length ? base.filter((row) => picked.includes(row.tier)) : base;
  return sortRows(rows, activeSortKeys());
}

// A single sort key throws away the previous one, but the question people actually ask is
// a chain: "same score → newest first". `data.js` has supported an array of keys all along;
// this is the UI that finally passes more than one.
function activeSortKeys() {
  const keys = [];
  const seen = new Set();
  for (const key of [state.sort, ...(state.sortChain || [])]) {
    if (!key || !key.column || seen.has(key.column)) continue;
    seen.add(key.column);
    keys.push({ column: key.column, direction: key.direction === "asc" ? "asc" : "desc" });
  }
  return keys;
}

// Plain click: replace the chain and flip asc/desc. Shift-click: add this column as another
// key, flip it in place, and drop it again on the third click.
function cycleSort(column, append) {
  const keys = activeSortKeys();
  const current = keys.find((key) => key.column === column);
  const next = !current ? "desc" : current.direction === "desc" ? "asc" : "desc";
  if (!append) {
    state.sort = { column, direction: next };
    state.sortChain = [];
    return;
  }
  if (current && current.direction === "asc" && keys.length > 1) {
    const rest = keys.filter((key) => key.column !== column);
    state.sort = rest[0];
    state.sortChain = rest.slice(1);
    return;
  }
  const position = current ? keys.findIndex((key) => key.column === column) : keys.length;
  const chain = keys.filter((key) => key.column !== column);
  chain.splice(Math.min(position, chain.length), 0, { column, direction: next });
  state.sort = chain[0];
  state.sortChain = chain.slice(1);
}

function renderExplorer() {
  const base = baseRows();
  const rows = filteredRows(base);
  state.lastCount = rows.length;
  const pages = Math.max(1, Math.ceil(rows.length / state.pageSize));
  if (state.page >= pages) state.page = 0;
  const pageRows = rows.slice(state.page * state.pageSize, (state.page + 1) * state.pageSize);

  clear(els.view);
  const layout = h("div", { class: "explorer" });
  layout.appendChild(filterPanel());
  const main = h("div", { class: "explorer-main" });
  main.appendChild(quickbar(base));
  main.appendChild(toolbar(rows.length));
  // Active filter chips: show what's currently filtering so the user can see and remove.
  const chips = [];
  if (state.query.text) chips.push({ label: `搜索: ${state.query.text}`, remove: () => { state.query.text = ""; renderExplorer(); pushUrlState(); } });
  if (state.query.tiers && state.query.tiers.length) chips.push({ label: `档位: ${state.query.tiers.join(",")}`, remove: () => { state.query.tiers = []; renderExplorer(); pushUrlState(); } });
  for (const [key, allowed] of Object.entries(state.query.facets || {})) {
    if (allowed && allowed.length) chips.push({ label: `${key}: ${allowed.join(",")}`, remove: () => { delete state.query.facets[key]; renderExplorer(); pushUrlState(); } });
  }
  if (state.query.hideClosed) chips.push({ label: "隐藏已关闭", remove: () => { state.query.hideClosed = false; setPref("hideClosed", false); renderExplorer(); pushUrlState(); } });
  if (state.query.hideVisited) chips.push({ label: "隐藏已看过", remove: () => { state.query.hideVisited = false; setPref("hideVisited", false); renderExplorer(); pushUrlState(); } });
  if (chips.length) {
    const chipBar = h("div", { class: "filter-chips" }, [
      ...chips.map((c) => h("span", { class: "filter-chip" }, [c.label, h("button", { type: "button", onclick: c.remove, text: "×" })])),
      h("button", { type: "button", class: "ghost", onclick: () => { state.query = freshQuery({ hideClosed: false, hideVisited: false }); state.page = 0; renderExplorer(); pushUrlState(); }, text: "清除全部" }),
    ]);
    main.appendChild(chipBar);
  }
  main.appendChild(tableBlock(pageRows, rows));
  if (state.colsConfigOpen) {
    const configPanel = h("div", { class: "card col-config" }, [
      h("h3", {}, "列配置"),
      h("div", { class: "checks" }, TABLE_HEAD.filter((c) => c.key !== "link" && c.key !== "check").map((col) =>
        h("label", { class: "check" }, [
          h("input", {
            type: "checkbox",
            checked: state.visibleCols.includes(col.key),
            onchange: (event) => {
              if (event.target.checked) state.visibleCols.push(col.key);
              else state.visibleCols = state.visibleCols.filter((k) => k !== col.key);
              setPref("visibleCols", state.visibleCols);
              renderExplorer();
            },
          }),
          col.label,
        ])
      )),
      h("div", { class: "row" }, [
        h("button", { type: "button", class: "ghost", onclick: () => { state.visibleCols = ["title", "company", "location", "score", "salary", "published_at"]; setPref("visibleCols", state.visibleCols); renderExplorer(); }, text: "恢复默认" }),
        h("button", { type: "button", class: "ghost", onclick: () => { state.colsConfigOpen = false; renderExplorer(); }, text: "关闭" }),
      ]),
    ]);
    main.appendChild(configPanel);
  }
  main.appendChild(pager(pages, rows.length));
  layout.appendChild(main);
  els.view.appendChild(layout);
  const backdrop = h("div", { class: "drawer-backdrop", id: "drawer-backdrop", onclick: () => closeJob() });
  const drawer = h("aside", {
    class: "drawer",
    id: "drawer",
    role: "dialog",
    "aria-modal": "true",
    "aria-labelledby": "drawer-title",
    "aria-hidden": "true",
    inert: true,
  }, [
    h("button", { type: "button", class: "ghost drawer-close", onclick: () => closeJob(), "aria-label": "关闭详情", text: "×" }),
    h("div", { id: "drawer-body" }),
  ]);
  // Tab must stay inside the dialog: the table behind it is still in the tab order and a
  // keyboard user would otherwise walk invisibly off-panel.
  drawer.addEventListener("keydown", (event) => {
    if (event.key === "Tab") trapFocus(drawer, event);
  });
  els.view.appendChild(backdrop);
  els.view.appendChild(drawer);
  if (state.activeJob) openDrawer(state.activeJob, false);
}

// Tier chips double as the colour legend and as filters; the sort box and the two hide
// toggles are the everyday "work through the list" controls.
function quickbar(base) {
  const counts = Object.fromEntries(TIERS.map((tier) => [tier.id, 0]));
  for (const row of base) counts[row.tier] += 1;
  const picked = state.query.tiers;

  const apply = () => {
    state.page = 0;
    renderExplorer();
  };
  const chip = (id, label, count, rule, on, onclick) =>
    h("button", {
      type: "button",
      class: `chip tier-${id}${on ? " is-on" : ""}`,
      "aria-pressed": String(on),
      title: rule,
      onclick,
    }, [h("span", { class: "swatch" }), `${label} `, h("b", { text: String(count) })]);

  const chips = [
    chip("all", "全部", base.length, "不按档位过滤", picked.length === 0, () => {
      state.query.tiers = [];
      apply();
    }),
    ...TIERS.map((tier) =>
      chip(tier.id, tier.label, counts[tier.id], tier.rule, picked.includes(tier.id), () => {
        state.query.tiers = picked.includes(tier.id) ? picked.filter((id) => id !== tier.id) : [...picked, tier.id];
        apply();
      })
    ),
  ];

  const toggle = (key, label) =>
    h("label", { class: "check" }, [
      h("input", {
        type: "checkbox",
        checked: state.query[key],
        onchange: (event) => {
          state.query[key] = event.target.checked;
          setPref(key, event.target.checked);
          apply();
        },
      }),
      label,
    ]);

  const known = SORT_CHOICES.some(([column]) => column === state.sort.column);
  const sortBox = h("label", { class: "muted" }, [
    "排序 ",
    h("select", {
      onchange: (event) => {
        state.sort = { column: event.target.value, direction: "desc" };
        state.sortChain = [];
        state.page = 0;
        renderExplorer();
        pushUrlState();
      },
    }, [
      ...(known ? [] : [h("option", { value: state.sort.column, selected: true }, "按表头排序")]),
      ...SORT_CHOICES.map(([column, label]) => h("option", { value: column, selected: column === state.sort.column }, label)),
    ]),
  ]);

    const densityBox = h("label", { class: "muted" }, [
    "density ",
    h("select", {
      onchange: (event) => { state.density = event.target.value; applyDensity(); },
    }, [
      h("option", { value: "compact", selected: state.density === "compact" }, "compact"),
      h("option", { value: "standard", selected: state.density === "standard" }, "standard"),
      h("option", { value: "loose", selected: state.density === "loose" }, "loose"),
    ]),
  ]);
return h("div", { class: "quickbar" }, [
    h("div", { class: "chips", role: "group", "aria-label": "按档位过滤" }, chips),
    h("div", { class: "row" }, [
      toggle("hideClosed", "隐藏已关闭"),
      toggle("hideVisited", "隐藏已看过"),
      sortBox,
      densityBox,
      h("button", {
        type: "button",
        class: "secondary",
        onclick: exportIntake,
        title: "导出「必投 · 未投递 · 未看过 · 非法国岗位需有签证担保」的岗位清单，交给 Obsidian 申请流水线",
        text: `导出待办 ${intakeRows().length}`,
      }),
    ]),
  ]);
}

function toolbar(count) {
  const allOnPageChecked = count > 0 && pageRowsAreAllSelected();
    const colBtn = h("button", { type: "button", class: "secondary", onclick: () => { state.colsConfigOpen = !state.colsConfigOpen; renderExplorer(); }, text: "列配置" });
return h("div", { class: "toolbar" }, [
    h("span", { class: "muted sel-count", text: `筛选后 ${count} 条 · 选中 ${state.selected.size} 条` }),
    h("label", { class: "check" }, [
      h("input", {
        type: "checkbox",
        class: "select-page",
        checked: allOnPageChecked,
        onchange: (event) => togglePage(event.target.checked),
      }),
      "全选本页",
    ]),
    h("label", { class: "check" }, [
      h("input", {
        type: "checkbox",
        class: "legacy-only",
        checked: state.legacyOnly,
        onchange: (event) => {
          state.legacyOnly = event.target.checked;
          setPref("legacyOnly", event.target.checked);
        },
      }),
      "导出只用 latest.csv 的 31 列",
    ]),

  colBtn,
    h("div", { class: "row bulk-actions", hidden: state.selected.size === 0 }, [
      h("button", { type: "button", class: "secondary", onclick: () => bulkStatus("已投递"), text: "批量标为已投" }),
      h("button", { type: "button", class: "secondary", onclick: () => bulkStatus("放弃"), text: "批量放弃" }),
      h("button", { type: "button", class: "ghost", onclick: () => { state.selected.clear(); syncSelectionUi(state.lastCount); }, text: "清空选择" }),
    ]),
    h("button", { type: "button", onclick: () => exportCsv("all", null), text: "下载全部 CSV" }),
    h("button", { type: "button", onclick: () => exportCsv("filtered", filteredRows()), text: "下载筛选结果 CSV" }),
    h("button", {
      type: "button",
      class: "download-selected",
      disabled: state.selected.size === 0,
      onclick: () => exportCsv("selected", state.rows.filter((row) => state.selected.has(row.job_id))),
      text: "下载选中 CSV",
    }),
  ]);
}

// Selection changes touch only the nodes that depend on them. Rebuilding the table on
// every click replaced the checkbox the pointer was still on, so a fast second click
// could be lost, and it threw away the scroll position.
function syncSelectionUi(count) {
  const scope = els.view;
  const counter = scope.querySelector(".sel-count");
  if (counter) counter.textContent = `筛选后 ${count} 条 · 选中 ${state.selected.size} 条`;
  const pageBox = scope.querySelector(".select-page");
  if (pageBox) pageBox.checked = count > 0 && pageRowsAreAllSelected();
  const downloadButton = scope.querySelector(".download-selected");
  if (downloadButton) downloadButton.disabled = state.selected.size === 0;
  const bulk = scope.querySelector(".bulk-actions");
  if (bulk) bulk.hidden = state.selected.size === 0;
  for (const box of scope.querySelectorAll("tr.job-row input[type=checkbox]")) {
    box.checked = state.selected.has(box.dataset.job);
  }
}

// Selection used to exist only to export CSV. Triaging forty rows one row at a time is the
// actual work, so selection now writes the same overlay (localStorage) in one go.
function bulkStatus(status) {
  const ids = [...state.selected];
  if (!ids.length) return;
  state.skipOverlayRender = true;
  for (const id of ids) state.overlay.set(id, { status });
  state.skipOverlayRender = false;
  state.selected.clear();
  renderExplorer();
}

function pageRowsAreAllSelected() {
  const rows = filteredRows().slice(state.page * state.pageSize, (state.page + 1) * state.pageSize);
  return rows.length > 0 && rows.every((row) => state.selected.has(row.job_id));
}

function togglePage(checked) {
  const rows = filteredRows().slice(state.page * state.pageSize, (state.page + 1) * state.pageSize);
  for (const row of rows) {
    if (checked) state.selected.add(row.job_id);
    else state.selected.delete(row.job_id);
  }
  syncSelectionUi(state.lastCount);
}

function tableBlock(pageRows, allRows) {
  if (!allRows.length) {
    return h("p", { class: "muted" }, "没有符合当前条件的职位。放宽筛选或清空搜索词。");
  }
  const visibleSet = new Set(state.visibleCols || []);
  const visibleHead = TABLE_HEAD.filter((col) => col.key === "link" || col.key === "check" || visibleSet.has(col.key));
  const sortKeys = activeSortKeys();
  const head = h("tr", {}, [
    ...visibleHead.map((col) => {
      if (!col.sort) return h("th", { class: `col-${col.key}`, scope: "col", title: col.title }, col.label);
      const rank = sortKeys.findIndex((key) => key.column === col.sort);
      const active = rank >= 0;
      const key = active ? sortKeys[rank] : null;
      return h(
        "th",
        {
          class: `col-${col.key} sortable${active ? " sorted" : ""}`,
          scope: "col",
          "aria-sort": active ? (key.direction === "desc" ? "descending" : "ascending") : "none",
          onclick: (event) => {
            cycleSort(col.sort, event.shiftKey);
            state.page = 0;
            renderExplorer();
            pushUrlState();
          },
          title: `${col.title || `按「${col.label}」排序`}（Shift+点击：加为第二排序键）`,
        },
        [
          col.label,
          active ? (key.direction === "desc" ? " ↓" : " ↑") : "",
          active && sortKeys.length > 1 ? h("span", { class: "sort-rank", text: String(rank + 1) }) : null,
        ]
      );
    }),
  ]);

  const newDay = state.runs[0] && state.runs[0].completed_at ? String(state.runs[0].completed_at).slice(0, 10) : "";
  const body = pageRows.map((row) => jobRow(row, newDay));
  const cards = h("div", { class: "card-list" }, pageRows.map((row) => jobCard(row, newDay)));
  return h("div", { class: "table-block" }, [
    h("div", { class: "table-scroll" }, h("table", { class: "grid" }, [h("thead", {}, head), h("tbody", {}, body)])),
    cards,
  ]);
}

// Narrow screens get cards instead of a 17-column table squeezed off the edge: the same
// five things (what/where/when/score/act) at a size a phone can actually read.
function jobCard(row, newDay) {
  const tier = tierMeta(row.tier);
  const meta = [row.company, row.city || row.location, salaryText(row), shortDate(row.posted_day)].filter(Boolean);
  return h("article", { class: `job-card ${rowClass(row)}`, "data-job": row.job_id }, [
    h("div", { class: "job-card-head" }, [
      h("a", {
        href: "#",
        class: "job-title",
        onclick: (event) => {
          event.preventDefault();
          openJob(row.job_id);
        },
        text: row.title || "(无标题)",
      }),
      newDay && row.first_seen_day === newDay ? h("span", { class: "badge-new", text: "新" }) : null,
    ]),
    h("p", { class: "muted job-card-meta", text: meta.join(" · ") }),
    h("div", { class: "row" }, [
      h("span", { class: `score-chip tier-${row.tier}`, text: row.final_score === "" ? "—" : String(row.final_score) }),
      h("span", { class: `tier-tag tier-${row.tier}`, text: row.tier === "blocked" ? `✕ ${row.gate || tier.label}` : tier.label }),
      visaChip(row),
      row.url ? h("a", { href: safeUrl(row.url) || "#", target: "_blank", rel: "noopener", class: "ext", title: "原页", text: "↗" }) : null,
    ]),
  ]);
}

function rowClass(row) {
  const parts = ["job-row", `tier-${row.tier}`];
  if (row.status === "closed") parts.push("is-closed");
  if (state.visited.has(row.job_id)) parts.push("is-visited");
  if (state.activeJob === row.job_id) parts.push("is-active");
  const stage = STAGE_CLASS[state.overlay.get(row.job_id).status];
  if (stage) parts.push(stage);
  return parts.join(" ");
}

// The intake list is what the Obsidian application pipeline consumes: the jobs that are
// worth writing a cover letter for. The reader applies these rules by hand every day, so
// the machine applies exactly the same ones:
//   1. must-apply tier (through every gate, high enough score),
//   2. not applied to yet and not opened yet - those are the reader's own decisions,
//   3. outside France, proven visa sponsorship; silence is not proof.
// The browser holds the only record of "applied" and "opened" (localStorage), so the
// export is what carries that knowledge out of the page.
const APPLIED_STATES = ["已投递", "已回复", "面试中", "Offer", "拒绝", "放弃", "已关闭"];

function intakeRows() {
  // state.rows, not baseRows(): the to-do list is the whole actionable set, not whatever
  // the reader happens to be searching for right now.
  return state.rows.filter((row) => {
    if (row.tier !== "must") return false;
    if (state.visited.has(row.job_id)) return false;
    const status = state.overlay.get(row.job_id).status || "";
    if (APPLIED_STATES.includes(status)) return false;
    const country = String(row.country || "");
    if (country && country !== "France") return String(row.visa_status || "") === "sponsored";
    return true;
  });
}

function exportIntake() {
  const rows = intakeRows();
  const payload = {
    kind: "jobdash.intake",
    version: 1,
    exported_at: new Date().toISOString(),
    snapshot_run: state.manifest ? state.manifest.latest_run_completed_at || "" : "",
    criteria: {
      tier: "must",
      skip_visited: true,
      skip_applied: true,
      non_france_requires: "visa_status = sponsored",
    },
    jobs: rows.map((row) => ({
      job_id: row.job_id,
      title: row.title,
      company: row.company,
      location: row.location,
      country: row.country,
      remote: row.remote,
      employment_type: row.employment_type,
      salary: row.salary,
      url: row.url,
      final_score: row.final_score,
      tier: row.tier,
      decision: row.decision,
      visa_status: row.visa_status || "",
      visa_evidence: row.visa_evidence || "",
      published_at: row.published_at,
      first_seen_at: row.first_seen_at,
      description: (state.descriptions && state.descriptions[row.job_id]) || "",
    })),
  };
  download(`jobdash-intake-${stamp()}.json`, JSON.stringify(payload, null, 2), "application/json;charset=utf-8");
  setStatus(`已导出 ${rows.length} 条待办（必投 · 未投递 · 未看过 · 非法国岗位需有签证担保）`);
}

function scoreCell(row) {
  const tier = tierMeta(row.tier);
  const score = row.final_score === "" || row.final_score === undefined ? "—" : String(row.final_score);
  // A blocked row says *why* instead of just "blocked": that is the whole point of the tag.
  const tag = row.tier === "blocked" ? `✕ ${row.gate || tier.label}` : tier.label;
  const reason = [tier.rule, row.filter_reasons || row.hard_filter_reasons].filter(Boolean).join("\n");
  return h("td", { class: "col-score" }, [
    h("span", { class: `score-chip tier-${row.tier}`, title: reason, text: score }),
    h("span", { class: `tier-tag tier-${row.tier}`, title: reason, text: tag }),
    visaChip(row),
  ]);
}

// Visa sponsorship, read from the advert's own words by pipeline/signals/visa.py.
// French posts are silent (the badge would be noise on 3 000+ rows), and "unknown" is
// shown as unknown: an advert that never mentions sponsorship is not a yes.
const VISA_LABELS = {
  sponsored: { cls: "visa-ok", text: "担保✓" },
  not_sponsored: { cls: "visa-no", text: "无担保✕" },
  unknown: { cls: "visa-unknown", text: "担保?" },
};

function visaChip(row) {
  const status = String(row.visa_status || "");
  const label = VISA_LABELS[status];
  if (!label) return null;
  const title = row.visa_evidence
    ? `签证担保：${row.visa_evidence}`
    : "JD 里没有签证担保的说明";
  return h("span", { class: `visa-chip ${label.cls}`, title, text: label.text });
}

// "50000-70000 EUR/an" -> "50–70k €": same information in a third of the width.
function compactSalary(text) {
  const range = /^(\d{4,6})\s*-\s*(\d{4,6})\s*EUR\/an$/i.exec(text.trim());
  if (range) return `${Math.round(range[1] / 1000)}–${Math.round(range[2] / 1000)}k €`;
  return text.replace(/\s*EUR\/an/i, " €/an");
}

function salaryText(row) {
  if (String(row.salary || "").trim()) return compactSalary(String(row.salary));
  const min = Number(row.salary_gross_min);
  return min > 0 ? `≥ ${Math.round(min / 1000)}k €/年` : "";
}

function jobRow(row, newDay) {
  const overlay = state.overlay.get(row.job_id);
  const tr = h("tr", { class: rowClass(row), "data-job": row.job_id });
  const isNew = newDay && row.first_seen_day === newDay;

  const statusBox = h("select", {
    class: "mini-status",
    "aria-label": "我的申请状态",
    onchange: (event) => {
      // Update just this row: a full re-render would drop the scroll position mid-triage.
      state.skipOverlayRender = true;
      state.overlay.set(row.job_id, { status: event.target.value });
      state.skipOverlayRender = false;
      tr.className = rowClass(row);
      if (state.query.statuses.length) renderExplorer();
    },
  }, ["", ...STATUSES].map((status) => h("option", { value: status, selected: (overlay.status || "") === status }, status || "—")));

  const visibleSet = new Set(state.visibleCols || []);
  const cells = [];
  cells.push(h("td", { class: "col-link" }, externalLink(row, { rowNode: tr }) || h("span", { class: "muted", text: "\u2014" })));
  cells.push(h("td", { class: "col-check" }, h("input", {
    type: "checkbox",
    "data-job": row.job_id,
    checked: state.selected.has(row.job_id),
    onchange: (event) => {
      if (event.target.checked) state.selected.add(row.job_id);
      else state.selected.delete(row.job_id);
      syncSelectionUi(state.lastCount);
    },
  })));
  if (visibleSet.has("score")) cells.push(scoreCell(row));
  if (visibleSet.has("title")) cells.push(h("td", { class: "col-title" }, [
    h("a", {
      href: "#",
      class: "job-title",
      onclick: (event) => {
        event.preventDefault();
        openJob(row.job_id);
      },
      text: row.title || "(\u65e0\u6807\u9898)",
    }),
    isNew ? h("span", { class: "badge-new", title: "\u672c\u8f6e\u9996\u6b21\u51fa\u73b0", text: "\u65b0" }) : null,
  ]));
  if (visibleSet.has("company")) cells.push(h("td", { class: "col-company", text: row.company }));
  if (visibleSet.has("location")) cells.push(h("td", { class: "col-location", title: row.location }, [row.city || row.location, row.remote === "Yes" ? h("span", { class: "tag-remote", text: "\u8fdc\u7a0b" }) : null]));
  if (visibleSet.has("salary")) cells.push(h("td", { class: "col-salary", title: row.salary || "", text: salaryText(row) }));
  if (visibleSet.has("employment_type")) cells.push(h("td", { class: "col-employment_type", text: row.employment_type }));
  if (visibleSet.has("published_at")) cells.push(h("td", { class: "col-published_at", text: shortDate(row.posted_day) }));
  if (visibleSet.has("source")) cells.push(h("td", { class: "col-source", text: row.source }));
  if (visibleSet.has("status")) cells.push(h("td", { class: "col-status" }, row.status === "closed" ? h("span", { class: "tag-closed", text: "\u5df2\u5173\u95ed" }) : null));
  if (visibleSet.has("visa_status")) cells.push(h("td", { class: "col-visa_status" }, visaChip(row) || h("span", { class: "muted", text: "—" })));
  if (visibleSet.has("mine")) cells.push(h("td", { class: "col-mine" }, statusBox));
  tr.append(...cells);
  const actions = h("span", { class: "row-actions" }, [
    h("button", { type: "button", class: "ghost", onclick: () => openJob(row.job_id), title: "\u8be6\u60c5", text: "\u22ef" }),
    h("button", { type: "button", class: "ghost", onclick: () => { state.overlay.set(row.job_id, { status: "\u5df2\u6295\u9012" }); tr.className = rowClass(row); }, title: "\u6807\u4e3a\u5df2\u6295", text: "\u2713" }),
    h("button", { type: "button", class: "ghost", onclick: () => { const n = prompt("\u5907\u6ce8\uff1a", state.overlay.get(row.job_id).notes || ""); if (n !== null) state.overlay.set(row.job_id, { notes: n }); }, title: "\u5199\u5907\u6ce8", text: "\u270e" }),
    h("a", { href: row.url || "#", target: "_blank", rel: "noopener", class: "ghost", title: "\u539f\u9875", text: "\u2197" }),
  ]);
  tr.appendChild(actions);
  return tr;
}

function pager(pages, count) {
  return h("div", { class: "toolbar" }, [
    h("button", { type: "button", disabled: state.page === 0, onclick: () => { state.page -= 1; renderExplorer(); }, text: "上一页" }),
    h("span", { text: `${state.page + 1} / ${pages}` }),
    h("button", { type: "button", disabled: state.page >= pages - 1, onclick: () => { state.page += 1; renderExplorer(); }, text: "下一页" }),
    h("label", { class: "muted" }, [
      "每页 ",
      h("select", {
        onchange: (event) => {
          state.pageSize = Number(event.target.value);
          state.page = 0;
          renderExplorer();
        },
      }, [50, 100, 200, 500].map((size) => h("option", { value: size, selected: size === state.pageSize }, String(size)))),
    ]),
    h("span", { class: "muted", text: `共 ${count} 条` }),
  ]);
}

function filterPanel() {
  const panel = h("aside", { class: "filters" });
  panel.appendChild(
    h("input", {
      type: "search",
      class: "search",
      placeholder: "搜索标题/公司/地点/技能…",
      value: state.query.text,
      oninput: debounce((event) => {
        state.query.text = event.target.value;
        state.page = 0;
        renderExplorer();
        // The re-render replaces the input, which silently dropped focus after every
        // pause in typing. Hand it back to the new one with the caret at the end.
        const box = els.view.querySelector("input.search");
        if (box) {
          box.focus();
          box.setSelectionRange(box.value.length, box.value.length);
        }
      }, 250),
    })
  );

  panel.appendChild(
    h("label", { class: "check" }, [
      h("input", {
        type: "checkbox",
        checked: state.query.searchJd,
        onchange: async (event) => {
          state.query.searchJd = event.target.checked;
          if (event.target.checked && !state.descriptions) {
            setStatus("正在下载 JD 正文以支持全文搜索…");
            try {
              state.descriptions = await loadDescriptions(state.backend, state.manifest);
              setStatus(`JD 正文已缓存 ${Object.keys(state.descriptions).length} 条`);
            } catch (error) {
              showError(`JD 正文下载失败：${error.message}`);
              state.query.searchJd = false;
            }
          }
          renderExplorer();
        },
      }),
      "同时搜索 JD 正文（需另下载正文）",
    ])
  );

  for (const facet of ["country", "city", "company", "source", "employment_type", "seniority", "decision", "remote", "status", "salary_basis"]) {
    const entries = state.dataset.facets[facet] || [];
    if (!entries.length) continue;
    panel.appendChild(facetBlock(facet, entries));
  }

  panel.appendChild(
    h("details", { class: "filter-block" }, [
      h("summary", {}, "评分区间 / 发布日期"),
      h("div", { class: "row" }, [
        h("input", {
          type: "number", placeholder: "最低分", value: state.query.scoreRange[0] ?? "", step: "0.5",
          onchange: (event) => { state.query.scoreRange = [event.target.value, state.query.scoreRange[1]]; renderExplorer(); },
        }),
        h("input", {
          type: "number", placeholder: "最高分", value: state.query.scoreRange[1] ?? "", step: "0.5",
          onchange: (event) => { state.query.scoreRange = [state.query.scoreRange[0], event.target.value]; renderExplorer(); },
        }),
      ]),
      h("div", { class: "row" }, [
        h("input", { type: "date", value: state.query.dateRange.start, onchange: (event) => { state.query.dateRange.start = event.target.value; renderExplorer(); } }),
        h("input", { type: "date", value: state.query.dateRange.end, onchange: (event) => { state.query.dateRange.end = event.target.value; renderExplorer(); } }),
      ]),
    ])
  );

  panel.appendChild(
    h("details", { class: "filter-block" }, [
      h("summary", {}, `我的申请状态（本机 ${state.overlay.count()} 条）`),
      h(
        "div",
        { class: "checks" },
        ["(未标记)", ...STATUSES].map((status) =>
          h("label", { class: "check" }, [
            h("input", {
              type: "checkbox",
              checked: state.query.statuses.includes(status),
              onchange: (event) => {
                state.query.statuses = event.target.checked
                  ? [...state.query.statuses, status]
                  : state.query.statuses.filter((item) => item !== status);
                renderExplorer();
              },
            }),
            status,
          ])
        )
      ),
    ])
  );

  panel.appendChild(
    h("button", {
      type: "button",
      class: "reset",
      onclick: () => {
        state.query = freshQuery();
        setPref("hideClosed", false);
        setPref("hideVisited", false);
        state.page = 0;
        renderExplorer();
      },
      text: "清空全部筛选",
    })
  );
  return panel;
}

function facetBlock(facet, entries) {
  const limit = entries.length > 12 ? 12 : entries.length;
  const selected = state.query.facets[facet] || [];
  return h("details", { class: "filter-block", open: ["country", "source", "status", "decision"].includes(facet) }, [
    h("summary", {}, `${pretty(facet)}（${entries.length}）`),
    h(
      "div",
      { class: "checks" },
      entries.slice(0, limit).map(([value, count]) =>
        h("label", { class: "check" }, [
          h("input", {
            type: "checkbox",
            checked: selected.includes(value),
            onchange: (event) => {
              const current = new Set(state.query.facets[facet] || []);
              if (event.target.checked) current.add(value);
              else current.delete(value);
              state.query.facets[facet] = [...current];
              state.page = 0;
              renderExplorer();
            },
          }),
          `${value} (${count})`,
        ])
      )
    ),
    entries.length > limit ? h("span", { class: "muted", text: `另有 ${entries.length - limit} 项，用搜索框定位` }) : null,
  ]);
}

function openDrawer(jobId, focus = true) {
  const body = document.getElementById("drawer-body");
  if (!body) return;
  if (!state.lastFocus && document.activeElement && document.activeElement !== document.body) {
    state.lastFocus = document.activeElement;
  }
  clear(body);
  const block = detailBlock(jobId);
  if (block) body.appendChild(block);
  const drawer = document.getElementById("drawer");
  const backdrop = document.getElementById("drawer-backdrop");
  if (drawer) {
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    drawer.inert = false;
  }
  if (backdrop) backdrop.classList.add("open");
  if (focus) {
    const node = document.getElementById("detail");
    if (node) { node.tabIndex = -1; node.focus(); }
  }
}

// Keep Tab inside the drawer while it is open (there is no <dialog> here: the panel is a
// plain aside so it can stay in the document between renders).
function trapFocus(container, event) {
  const focusable = [...container.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
    .filter((node) => node.offsetParent !== null || node === document.activeElement);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  } else if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  }
}

function closeJob() {
  const jobId = state.activeJob;
  flushDrawerEdits(jobId);
  state.activeJob = "";
  const drawer = document.getElementById("drawer");
  const backdrop = document.getElementById("drawer-backdrop");
  if (drawer) {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    drawer.inert = true;
  }
  if (backdrop) backdrop.classList.remove("open");
  // Return focus where it came from, so closing the drawer does not dump the reader back
  // at the top of the document.
  const previous = state.lastFocus;
  state.lastFocus = null;
  if (previous && previous.isConnected) previous.focus();
  else if (jobId) {
    const row = document.querySelector('tr[data-job="' + jobId + '"]');
    const target = row ? row.querySelector("a.job-title") : null;
    if (target) target.focus();
  }
  pushUrlState();
}

// Closing the drawer throws away its DOM, and removing a focused field fires no `change`,
// so a half-typed note would vanish on Escape. Commit whatever is on screen first.
function flushDrawerEdits(jobId) {
  const body = document.getElementById("drawer-body");
  if (!body || !jobId) return;
  const current = state.overlay.get(jobId);
  const patch = {};
  const note = body.querySelector("textarea");
  const contact = body.querySelector('input[type="text"]');
  if (note && note.value !== (current.notes || "")) patch.notes = note.value;
  if (contact && contact.value !== (current.contact || "")) patch.contact = contact.value;
  if (!Object.keys(patch).length) return;
  state.skipOverlayRender = true;
  state.overlay.set(jobId, patch);
  state.skipOverlayRender = false;
}

function openJob(jobId) {
  state.visited.mark(jobId);
  state.activeJob = jobId;
  state.view = "explorer";
  bindTabs();
  // Do NOT re-render the table: opening a job is a selection, not a filter change.
  // Re-rendering rebuilt the whole grid, dropped the scroll position, and cost a
  // full filteredRows() + sortRows() pass on every click.
  openDrawer(jobId);
  pushUrlState();
}

function detailBlock(jobId) {
  const row = state.rows.find((item) => item.job_id === jobId);
  if (!row) return h("p", { class: "muted" }, "这条职位不在当前快照里。");
  const overlay = state.overlay.get(jobId);
  const groups = DETAIL_GROUPS.map(([title, columns]) =>
    h("div", { class: "detail-group" }, [
      h("h3", {}, title),
      h(
        "dl",
        { class: "kv" },
        columns.flatMap((column) => [h("dt", {}, pretty(column)), h("dd", {}, detailValue(row, column))])
      ),
    ])
  );

  const tier = tierMeta(row.tier);
  const why = [tier.rule, row.filter_reasons, row.hard_filter_reasons].filter(Boolean).join(" · ");
  return h("section", { class: "card detail", id: "detail" }, [
    h("h2", { id: "drawer-title" }, row.title || "(无标题)"),
    h("p", { class: "muted" }, [`${row.company || "—"} · ${row.location || "—"}`, " ", externalLink(row, { text: "打开原招聘页 ↗", className: "" })]),
    h("p", { class: "detail-tier" }, [
      h("span", { class: `score-chip tier-${row.tier}`, text: row.final_score === "" ? "—" : String(row.final_score) }),
      h("span", { class: `tier-tag tier-${row.tier}`, text: row.tier === "blocked" ? `✕ ${row.gate || tier.label}` : tier.label }),
      visaChip(row),
      h("span", { class: "muted", text: why }),
    ]),
    h("div", { class: "detail-columns" }, [h("div", { class: "detail-fields" }, groups), jdBlock(row)]),
    h("div", { class: "overlay-editor" }, [
      h("h3", {}, "我的申请状态（只存本机浏览器）"),
      h("div", { class: "row" }, [
        h("select", {
          onchange: (event) => state.overlay.set(jobId, { status: event.target.value }),
        }, ["", ...STATUSES].map((status) => h("option", { value: status, selected: (overlay.status || "") === status }, status || "（未标记）"))),
        h("input", {
          type: "text", placeholder: "联系人 / 邮箱", value: overlay.contact || "",
          onchange: (event) => state.overlay.set(jobId, { contact: event.target.value }),
        }),
      ]),
      h("textarea", {
        rows: 3, placeholder: "备注：只存 localStorage，不会上传", value: overlay.notes || "",
        onchange: (event) => state.overlay.set(jobId, { notes: event.target.value }),
      }),
      overlay.updated_at ? h("span", { class: "muted", text: `本机记录更新于 ${overlay.updated_at}` }) : null,
    ]),
  ]);
}

// URL fields show as a short, clickable host name rather than the full (often very long,
// tracking-laden) address; the full URL is in the tooltip.
function detailValue(row, column) {
  const text = cellText(row, column);
  if (!text) return "—";
  if (column === "canonical_url" || column === "url") {
    const href = safeUrl(text);
    if (href) {
      return h("a", {
        href,
        target: "_blank",
        rel: "noopener noreferrer",
        title: href,
        onclick: () => state.visited.mark(row.job_id),
        text: `${hostOf(href)} ↗`,
      });
    }
  }
  return text;
}

function jdBlock(row) {
  const container = h("div", { class: "detail-jd" }, [h("h3", {}, "职位描述原文")]);
  const finish = (text) => container.appendChild(h("pre", { class: "jd" }, text || "（爬虫未取到正文）"));
  if (state.descriptions) {
    finish(state.descriptions[row.job_id] || "");
    return container;
  }
  container.appendChild(h("button", {
    type: "button",
    onclick: async (event) => {
      event.target.disabled = true;
      try {
        state.descriptions = await loadDescriptions(state.backend, state.manifest);
        renderExplorer();
      } catch (error) {
        showError(`正文加载失败：${error.message}`);
        event.target.disabled = false;
      }
    },
    text: "加载 JD 正文",
  }));
  return container;
}

// ----------------------------------------------------------- history

function renderHistory() {
  clear(els.view);
  if (!state.runs.length) {
    els.view.appendChild(section("爬取历史", [h("p", { class: "muted" }, "还没有任何一轮运行记录。爬虫每跑一次，这里就累积一条（历史存在私有仓的 dashboard-data 分支里）。")]));
    return;
  }
  const latest = state.runs[0];
  const previous = state.runs[1] || null;

  els.view.appendChild(
    section("最近一轮", [
      kpiGrid([
        ["运行状态", latest.status || "—", latest.completed_at || ""],
        ["本轮抓取", latest.scraped ?? "—", `进入排名 ${latest.ranked ?? "—"} · 落库 ${latest.job_records ?? "—"}`],
        ["新增岗位", latest.new_records ?? "—", `内容有变 ${latest.updated_records ?? "—"} · 关闭 ${latest.closed_records ?? "—"}`],
        ["耗时", latest.duration_sec ? `${Math.round(latest.duration_sec)} 秒` : "—", `未再见 ${latest.kept_unseen ?? "—"}`],
      ]),
    ])
  );

  if (previous) {
    els.view.appendChild(section("本轮 vs 上一轮", comparisonBlock(latest, previous)));
  } else {
    els.view.appendChild(section("本轮 vs 上一轮", [h("p", { class: "muted" }, "只有一轮记录，无法比较。再跑一次爬虫工作流后这里会出现对比。")]));
  }

  els.view.appendChild(
    section("每轮抓取量", lineChart([{ name: "scraped", points: points("scraped") }, { name: "ranked", points: points("ranked") }], { title: "", height: 240 }))
  );

  els.view.appendChild(section("失败与来源健康", failureBlock()));
  els.view.appendChild(section("运行明细", runsTable()));
  els.view.appendChild(section("切换到历史快照", refPicker()));
}

function points(field) {
  return state.runs
    .map((run) => {
      const day = toOrdinal(String(run.completed_at || "").slice(0, 10));
      return day === null ? null : [day, Number(run[field] || 0)];
    })
    .filter(Boolean)
    .reverse();
}

function comparisonBlock(latest, previous) {
  const day = String(latest.completed_at || "").slice(0, 10);
  const newJobs = state.rows.filter((row) => String(row.first_seen_at || "").slice(0, 10) === day);
  const delta = (key) => {
    const now = Number(latest[key] || 0);
    const before = Number(previous[key] || 0);
    return `${now - before >= 0 ? "+" : ""}${round(now - before)}`;
  };
  return [
    h("p", {}, [
      `抓取 ${delta("scraped")} · 进榜 ${delta("ranked")} · 落库总量 ${delta("job_records")}（相对 ${previous.completed_at}）`,
    ]),
    newJobs.length
      ? h("div", {}, [
          h("h3", {}, `本轮首次出现的 ${newJobs.length} 条`),
          listBlock(newJobs.slice(0, 20), (row) => `${row.title} · ${row.company} · ${row.final_score} 分`),
        ])
      : h("p", { class: "muted" }, "本轮没有首次出现的岗位。"),
  ];
}

function round(value) {
  return Math.round(value * 10) / 10;
}

function failureBlock() {
  const counts = new Map();
  for (const run of state.runs.slice(0, 10)) {
    for (const phase of run.phases || []) {
      for (const [category, value] of Object.entries(phase.errors_by_category || {})) {
        counts.set(`${phase.phase}/${category}`, (counts.get(`${phase.phase}/${category}`) || 0) + Number(value));
      }
    }
  }
  if (!counts.size) {
    return h("p", { class: "muted" }, "最近 10 轮没有分类错误记录。来源全绿不代表有货，请看每轮抓取量。");
  }
  return barChart([...counts.entries()].sort((a, b) => b[1] - a[1]), { title: "错误类别（phase/category）" });
}

function runsTable() {
  const head = h("tr", {}, ["完成时间", "状态", "抓取", "过滤后", "进榜", "落库", "新增", "变更", "关闭", "耗时秒", "来源分布", "错误"].map((label) => h("th", {}, label)));
  const body = state.runs.slice(0, 40).map((run) =>
    h("tr", {}, [
      h("td", {}, run.completed_at || ""),
      h("td", {}, run.status || ""),
      h("td", {}, String(run.scraped ?? "")),
      h("td", {}, String(run.filtered ?? "")),
      h("td", {}, String(run.ranked ?? "")),
      h("td", {}, String(run.job_records ?? "")),
      h("td", {}, String(run.new_records ?? "")),
      h("td", {}, String(run.updated_records ?? "")),
      h("td", {}, String(run.closed_records ?? "")),
      h("td", {}, run.duration_sec ? String(Math.round(run.duration_sec)) : ""),
      h("td", {}, Object.entries(run.sources || {}).map(([k, v]) => `${k}:${v}`).join(" ")),
      h("td", {}, String((run.errors || []).length)),
    ])
  );
  return h("div", { class: "table-scroll" }, h("table", { class: "grid" }, [h("thead", {}, head), h("tbody", {}, body)]));
}

function refPicker() {
  const box = h("div", {}, h("button", { type: "button", onclick: loadRefs, text: "列出可切换的历史快照" }));
  return box;

  async function loadRefs(event) {
    event.target.disabled = true;
    try {
      const refs = await state.backend.refs();
      clear(box);
      box.appendChild(
        h("select", {
          onchange: async (change) => {
            const ref = change.target.value;
            if (!ref) return;
            const repo = defaultRepo();
            setStatus(`正在切换到快照 ${ref}…`);
            state.backend = createGithubBackend({ ...repo, ref, token: getToken() });
            await reload();
          },
        }, [h("option", { value: "" }, "选择快照提交…"), ...refs.map((item) => h("option", { value: item.label }, `${item.label} · ${item.title}`))])
      );
      box.appendChild(h("p", { class: "muted" }, "切换后表格与总览显示该提交里的数据；切回最新用上方刷新按钮。"));
    } catch (error) {
      showError(`读取历史快照失败：${error.message}`);
    }
  }
}

// ----------------------------------------------------------- settings

function renderSettings() {
  clear(els.view);
  els.view.appendChild(h("section", { class: "card" }, [
    h("h2", {}, "数据健康（历史运行）"),
    h("p", { class: "muted" }, "爬虫运行记录与数据健康。正常情况下不需要查看。"),
    h("button", { type: "button", class: "secondary", onclick: () => { state.view = "history"; bindTabs(); render(); }, text: "打开历史运行视图" }),
  ]));
  const manifest = state.manifest || {};
  els.view.appendChild(
    section("这份数据从哪来", [
      h("dl", { class: "kv" }, [
        h("dt", {}, "私有仓数据分支"),
        h("dd", {}, `${defaultRepo().owner}/${defaultRepo().repo} @ ${defaultRepo().ref}`),
        h("dt", {}, "最近一轮完成时间"),
        h("dd", {}, manifest.latest_run_completed_at || "—"),
        h("dt", {}, "构建来源"),
        h("dd", {}, JSON.stringify(manifest.source || {})),
        h("dt", {}, "payload / schema 版本"),
        h("dd", {}, `${manifest.payload_version} / ${manifest.schema_version}`),
        h("dt", {}, "文件与体积"),
        h("dd", {}, Object.entries(manifest.files || {}).map(([name, meta]) => `${name} ${Math.round(meta.bytes / 1024)}KB (${meta.rows} 行)`).join(" · ")),
        h("dt", {}, "列数"),
        h("dd", {}, `${(manifest.columns || []).length} 列，其中正文单独存放在 details 文件`),
      ]),
    ])
  );

  els.view.appendChild(
    section("令牌与权限", [
      h("p", {}, `本机${getToken() ? "已保存" : "尚未保存"}访问令牌。令牌只用于向 api.github.com 读取 ${defaultRepo().repo} 的 ${defaultRepo().ref} 分支。`),
      h("ul", { class: "muted" }, [
        h("li", {}, "应当只授予 Contents: Read-only，且仅限 job_pipeline 一个仓库；不要使用可写入的令牌。"),
        h("li", {}, "令牌不进 URL、不进日志、不进任何仓库；本站代码里没有任何令牌字面量。"),
        h("li", {}, "浏览器端令牌方案的风险：如果这个页面被注入脚本（XSS），令牌会被读走。它是「只让我和 GitHub 之间」的门，不是严格意义的身份系统。"),
        h("li", {}, "GitHub 对私有仓库不提供 Pages 站点（需要组织 + Enterprise Cloud），所以站点壳必须是公开的，而数据留在私有仓由令牌读取。"),
      ]),
      h("div", { class: "row" }, [
        h("button", {
          type: "button",
          onclick: () => {
            clearToken();
            renderSettings();
            setStatus("已清除本机令牌。");
          },
          text: "清除本机令牌",
        }),
        h("button", { type: "button", onclick: reload, text: "重新加载快照" }),
      ]),
    ])
  );

  els.view.appendChild(
    section("我的申请状态（只在本机）", [
      h("p", { class: "muted" }, `${state.overlay.count()} 条本机记录，${state.visited.count()} 个岗位被标记为已看过。这些数据从不进入发布快照，也不上传。`),
      h("div", { class: "row" }, [
        h("button", {
          type: "button",
          onclick: () => {
            const payload = JSON.parse(state.overlay.exportText());
            payload.visited = state.visited.all();
            download(`jobdash-notes-${stamp()}.json`, JSON.stringify(payload, null, 2), "application/json");
          },
          text: "导出备注 JSON（含已看过）",
        }),
        h("button", {
          type: "button",
          onclick: () => {
            if (window.confirm("确定清除全部「已看过」标记？备注和申请状态不受影响。")) state.visited.clear();
            renderSettings();
          },
          text: "清除已看标记",
        }),
        h("label", { class: "file" }, [
          "导入备注 JSON",
          h("input", { type: "file", accept: "application/json", onchange: importNotes }),
        ]),
        h("button", {
          type: "button",
          onclick: () => {
            if (window.confirm("确定清除本机全部申请状态与备注？此操作不可撤销，建议先导出。")) state.overlay.clear();
            renderSettings();
          },
          text: "清除本机备注",
        }),
      ]),
    ])
  );

  els.view.appendChild(
    section("不公开的内容", [
      h("p", { class: "muted" }, `发布器被策略强制排除的私人字段：${(manifest.private_columns_excluded || []).join(", ") || "（清单为空）"}`),
      h("p", { class: "muted" }, "申请状态、备注、联系人由上面的本机层保存；快照里根本没有这些列，因此不存在「误发布」路径。"),
    ])
  );
}

async function importNotes(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  try {
    const text = await file.text();
    const count = state.overlay.importText(text);
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed.visited === "object") state.visited.merge(parsed.visited);
    setStatus(`已导入 ${count} 条本机备注。`);
    renderSettings();
  } catch (error) {
    showError(`导入失败：文件不是本导出的 JSON（${error.message}）`);
  }
  event.target.value = "";
}

// ----------------------------------------------------------- downloads

async function exportCsv(kind, rows) {
  const target = kind === "all" ? state.rows : rows || [];
  if (!target.length) {
    showError("没有可导出的行。");
    return;
  }
  if (!state.descriptions) {
    setStatus("导出需要 JD 正文，正在下载…");
    try {
      state.descriptions = await loadDescriptions(state.backend, state.manifest);
    } catch (error) {
      showError(`正文下载失败，改为导出不含正文的 CSV：${error.message}`);
    }
  }
  const detailColumn = state.manifest.detail_column;
  const headerMap = state.manifest.legacy_csv_headers || {};
  let columns;
  let names = headerMap;

  if (state.legacyOnly && (state.manifest.legacy_column_order || []).length) {
    // Same header set and the same column order as output/latest.csv.
    const byHeader = new Map(Object.entries(headerMap).map(([column, header]) => [header, column]));
    const pairs = state.manifest.legacy_column_order
      .filter((header) => byHeader.has(header) && (state.descriptions || header !== "Description"))
      .map((header) => [byHeader.get(header), header]);
    columns = pairs.map(([column]) => column);
    names = Object.fromEntries(pairs);
  } else {
    columns = (state.manifest.columns || state.columns).filter(
      (column) => state.descriptions || column !== detailColumn
    );
  }

  const payload = state.descriptions
    ? target.map((row) => ({ ...row, [detailColumn]: state.descriptions[row.job_id] || "" }))
    : target;
  const name = `jobs-${kind}-${stamp()}.csv`;
  download(name, toCsv(payload, columns, names));
  setStatus(
    `已导出 ${target.length} 行 × ${columns.length} 列到 ${name}（UTF-8 BOM；${
      state.legacyOnly ? "列名与顺序同 output/latest.csv" : "全字段，命名列沿用 latest.csv"
    }）`
  );
}

// ----------------------------------------------------------- helpers

function debounce(fn, wait) {
  let timer = null;
  return (event) => {
    const value = event.target;
    clearTimeout(timer);
    timer = setTimeout(() => fn({ target: value }), wait);
  };
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
