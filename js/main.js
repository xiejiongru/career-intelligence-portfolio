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
import { cityOf, createDataset, filterRows, sortRows, statsFor } from "./data.js";
import { barChart, histogram, lineChart, toOrdinal } from "./charts.js";
import { download, stamp, toCsv } from "./csv.js";
import { STATUSES, createOverlay } from "./overlay.js";

const VIEWS = ["overview", "explorer", "history", "settings"];
const TABLE_COLUMNS = [
  "title",
  "company",
  "country",
  "location",
  "salary",
  "published_at",
  "source",
  "final_score",
  "decision",
  "seniority",
  "employment_type",
  "remote",
  "status",
  "first_seen_at",
  "last_seen_at",
  "url",
];
const DETAIL_GROUPS = [
  ["职位身份", ["job_id", "source", "source_job_id", "canonical_url", "status", "content_hash", "schema_version"]],
  ["基本信息", ["title", "company", "location", "country", "employment_type", "remote", "salary", "published_at"]],
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
  query: { text: "", facets: {}, scoreRange: [null, null], dateRange: { start: "", end: "" }, statuses: [], searchJd: false },
  sort: { column: "final_score", direction: "desc" },
  page: 0,
  pageSize: 50,
  selected: new Set(),
  activeJob: "",
  legacyOnly: getPrefs().legacyOnly === true,
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

function pretty(name) {
  return name.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function cellText(row, column) {
  if (column === "url") return row.url || "";
  const value = row[column];
  return value === undefined || value === null ? "" : String(value);
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
  bindTabs();
  state.overlay.onChange(() => {
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

function render() {
  clear(els.view);
  if (!state.manifest) {
    els.view.appendChild(h("p", { class: "muted" }, "还没有加载到数据。"));
    return;
  }
  els.snapinfo.textContent = labelFromManifest(state.manifest);
  if (state.view === "overview") renderOverview();
  else if (state.view === "explorer") renderExplorer();
  else if (state.view === "history") renderHistory();
  else renderSettings();
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

function renderOverview() {
  const rows = state.rows;
  const stats = statsFor(rows);
  const latest = state.runs[0] || {};
  const seenDay = latest.completed_at ? String(latest.completed_at).slice(0, 10) : "";
  const newThisRun = rows.filter((row) => seenDay && String(row.first_seen_at || "").slice(0, 10) === seenDay).length;

  clear(els.view);
  els.view.appendChild(
    section("市场总览", [
      kpiGrid([
        ["累计职位", stats.total, `${stats.companies} 家公司 / ${stats.countries} 个国家`],
        ["最近一轮新增", latest.new_records ?? newThisRun, seenDay ? `首轮出现于 ${seenDay}` : "无历史轮次"],
        ["判定可投 apply", stats.apply, `待定 ${stats.needs_review} · 拦截 ${stats.skip}`],
        ["中位评分", stats.median_score ?? "—", `${stats.scored} 条已评分`],
        ["有薪资字段", stats.with_salary, stats.with_salary ? "薪资为原文照录，未做归一化" : "本轮数据里没有薪资，图表不画"],
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
  const withSalary = rows.filter((row) => String(row.salary || "").trim());
  if (!withSalary.length) {
    return section("薪资分布", [h("p", { class: "muted" }, `${rows.length} 条职位里 0 条带薪资原文。爬虫不编造薪资，所以这里没有图。`)]);
  }
  const counts = new Map();
  for (const row of withSalary) counts.set(row.salary.trim(), (counts.get(row.salary.trim()) || 0) + 1);
  return section(
    "薪资分布（原文，未归一化）",
    [barChart([...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12), { title: `${withSalary.length} 条带薪资` })]
  );
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

function filteredRows() {
  const rows = filterRows(state.rows, {
    text: state.query.text,
    facets: state.query.facets,
    scoreRange: state.query.scoreRange,
    dateRange: state.query.dateRange,
    overlayStatuses: state.query.statuses,
    getOverlay: (id) => state.overlay.get(id),
    searchJd: state.query.searchJd,
    descriptions: state.query.searchJd ? state.descriptions : null,
  });
  return sortRows(rows, state.sort);
}

function renderExplorer() {
  const rows = filteredRows();
  state.lastCount = rows.length;
  const pages = Math.max(1, Math.ceil(rows.length / state.pageSize));
  if (state.page >= pages) state.page = 0;
  const pageRows = rows.slice(state.page * state.pageSize, (state.page + 1) * state.pageSize);

  clear(els.view);
  const layout = h("div", { class: "explorer" });
  layout.appendChild(filterPanel());
  const main = h("div", { class: "explorer-main" });
  main.appendChild(toolbar(rows.length));
  main.appendChild(tableBlock(pageRows, rows));
  main.appendChild(pager(pages, rows.length));
  if (state.activeJob) main.appendChild(detailBlock(state.activeJob));
  layout.appendChild(main);
  els.view.appendChild(layout);
}

function toolbar(count) {
  const allOnPageChecked = count > 0 && pageRowsAreAllSelected();
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
  for (const box of scope.querySelectorAll("tr.job-row input[type=checkbox]")) {
    box.checked = state.selected.has(box.dataset.job);
  }
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
  const head = h("tr", {}, [
    h("th", {}, ""),
    ...TABLE_COLUMNS.map((column) =>
      h(
        "th",
        {
          class: `sortable${state.sort.column === column ? " sorted" : ""}`,
          onclick: () => {
            state.sort = { column, direction: state.sort.column === column && state.sort.direction === "desc" ? "asc" : "desc" };
            renderExplorer();
          },
          title: `按 ${pretty(column)} 排序`,
        },
        [pretty(column), state.sort.column === column ? (state.sort.direction === "desc" ? " ↓" : " ↑") : ""]
      )
    ),
    h("th", {}, "我的状态"),
    h("th", {}, "原链接"),
  ]);

  const body = pageRows.map((row) => {
    const overlay = state.overlay.get(row.job_id);
    return h("tr", { class: `job-row${state.activeJob === row.job_id ? " is-active" : ""}` }, [
      h("td", {}, h("input", {
        type: "checkbox",
        "data-job": row.job_id,
        checked: state.selected.has(row.job_id),
        onchange: (event) => {
          if (event.target.checked) state.selected.add(row.job_id);
          else state.selected.delete(row.job_id);
          syncSelectionUi(state.lastCount);
        },
      })),
      ...TABLE_COLUMNS.map((column) =>
        h("td", { class: column }, column === "url" ? (row.url ? h("a", { href: row.url, target: "_blank", rel: "noopener noreferrer", text: "链接" }) : "") : cellText(row, column))
      ),
      h("td", {}, overlay.status || ""),
      h("td", {}, h("button", { type: "button", onclick: () => openJob(row.job_id), text: "详情" })),
    ]);
  });

  return h("div", { class: "table-scroll" }, h("table", { class: "grid" }, [h("thead", {}, head), h("tbody", {}, body)]));
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

  for (const facet of ["country", "city", "company", "source", "employment_type", "seniority", "decision", "remote", "status"]) {
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
        state.query = { text: "", facets: {}, scoreRange: [null, null], dateRange: { start: "", end: "" }, statuses: [], searchJd: false };
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
  return h("details", { class: "filter-block" }, [
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

function openJob(jobId) {
  state.activeJob = jobId;
  state.view = "explorer";
  bindTabs();
  renderExplorer();
  const node = document.getElementById("detail");
  if (node) node.scrollIntoView({ block: "start" });
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
        columns.flatMap((column) => [h("dt", {}, pretty(column)), h("dd", {}, cellText(row, column) || "—")])
      ),
    ])
  );

  return h("section", { class: "card detail", id: "detail" }, [
    h("h2", {}, row.title || "(无标题)"),
    h("p", { class: "muted" }, [`${row.company || "—"} · ${row.location || "—"}`, " ", h("a", { href: row.url, target: "_blank", rel: "noopener noreferrer", text: "打开原招聘页" })]),
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
      h("p", { class: "muted" }, `${state.overlay.count()} 条本机记录。这些数据从不进入发布快照，也不上传。`),
      h("div", { class: "row" }, [
        h("button", { type: "button", onclick: () => download(`jobdash-notes-${stamp()}.json`, state.overlay.exportText(), "application/json"), text: "导出备注 JSON" }),
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
    const count = state.overlay.importText(await file.text());
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
