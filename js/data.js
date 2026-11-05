// Row model: faceting, filtering, sorting. Everything is derived from the loaded
// snapshot; nothing here talks to the network.

const NUMERIC = new Set([
  "final_score",
  "screening_score",
  "score_tech_match",
  "score_function_match",
  "score_domain_match",
  "score_experience_match",
  "score_growth_potential",
  "missed_runs",
]);

const TEXT_FIELDS = [
  "title",
  "company",
  "location",
  "summary",
  "gis_skills",
  "data_skills",
  "devops_skills",
  "programming_skills",
  "seniority",
  "employment_type",
];

export const FACETS = [
  "country",
  "location",
  "company",
  "source",
  "employment_type",
  "seniority",
  "decision",
  "status",
  "remote",
];

function norm(value) {
  // Accent folding matters here: French titles carry diacritics, and searching
  // "geomaticien" for "géomaticien" must not return nothing.
  return String(value ?? "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

export function cityOf(row) {
  const parts = String(row.location || "").split(",").map((part) => part.trim()).filter(Boolean);
  if (!parts.length) return "";
  const last = parts[parts.length - 1];
  // A trailing segment that is a country name is not a city.
  if (parts.length > 1 && /^[A-ZÀ-ž\s'-]+$/.test(last) && last.length <= 20 && isNaN(Number(last))) {
    return parts[parts.length - 2] || last;
  }
  return last;
}

export function dayOf(value) {
  const text = String(value || "").slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : "";
}

export function createDataset(rows) {
  const byCity = rows.map((row) => ({ ...row, city: cityOf(row), posted_day: dayOf(row.published_at), seen_day: dayOf(row.last_seen_at) }));
  const facets = {};
  for (const key of FACETS) {
    facets[key] = counts(byCity.map((row) => row[key] || "(空)"));
  }
  facets.city = counts(byCity.map((row) => row.city || "(空)"));
  return { rows: byCity, facets };
}

function counts(values) {
  const map = new Map();
  for (const value of values) map.set(value, (map.get(value) || 0) + 1);
  return [...map.entries()].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])));
}

export function filterRows(rows, query) {
  const text = (query.text || "").trim().toLowerCase();
  const terms = text.split(/\s+/).filter(Boolean);
  const fields = query.searchFields && query.searchFields.length ? query.searchFields : TEXT_FIELDS;
  const facets = query.facets || {};
  const scoreRange = query.scoreRange || null;
  const dateRange = query.dateRange || null;
  const statuses = query.overlayStatuses || null;
  const getOverlay = query.getOverlay || (() => "");
  const descriptions = query.descriptions || null;

  return rows.filter((row) => {
    for (const [key, allowed] of Object.entries(facets)) {
      if (!allowed || !allowed.length) continue;
      const value = key === "city" ? row.city : row[key] || "(空)";
      if (!allowed.includes(value)) return false;
    }
    if (scoreRange && !(inRange(Number(row.final_score) || 0, scoreRange))) return false;
    if (dateRange && dateRange.start && dateRange.end) {
      const day = row.posted_day || row.seen_day;
      if (!day || day < dateRange.start || day > dateRange.end) return false;
    }
    if (statuses && statuses.length) {
      const status = getOverlay(row.job_id).status || "(未标记)";
      if (!statuses.includes(status)) return false;
    }
    if (terms.length) {
      let haystack = fields.map((field) => norm(row[field])).join(" \u0001 ");
      if (descriptions) haystack += " \u0001 " + norm(descriptions[row.job_id] || "");
      if (!terms.every((term) => haystack.includes(term))) return false;
    }
    return true;
  });
}

function inRange(value, range) {
  const [min, max] = range;
  if (min !== null && min !== undefined && value < Number(min)) return false;
  if (max !== null && max !== undefined && value > Number(max)) return false;
  return true;
}

export function sortRows(rows, sort) {
  if (!sort || !sort.column) return rows;
  const { column, direction } = sort;
  const factor = direction === "asc" ? 1 : -1;
  const numeric = NUMERIC.has(column);
  return [...rows].sort((a, b) => {
    const left = numeric ? Number(a[column]) || 0 : String(a[column] ?? "");
    const right = numeric ? Number(b[column]) || 0 : String(b[column] ?? "");
    if (left === right) return String(a.job_id).localeCompare(String(b.job_id));
    return (left > right ? 1 : -1) * factor;
  });
}

export function statsFor(rows) {
  const withScore = rows.filter((row) => row.final_score !== "" && row.final_score !== undefined);
  const scores = withScore.map((row) => Number(row.final_score) || 0);
  const dated = rows.map((row) => row.posted_day).filter(Boolean).sort();
  return {
    total: rows.length,
    scored: withScore.length,
    companies: new Set(rows.map((row) => row.company).filter(Boolean)).size,
    countries: counts(rows.map((row) => row.country).filter(Boolean)).length,
    apply: rows.filter((row) => row.decision === "apply").length,
    needs_review: rows.filter((row) => row.decision === "needs_review").length,
    skip: rows.filter((row) => row.decision === "skip").length,
    with_salary: rows.filter((row) => String(row.salary || "").trim()).length,
    with_published_at: dated.length,
    median_score: scores.length ? quantile(scores.slice().sort((a, b) => a - b), 0.5) : null,
    newest: dated.length ? dated[dated.length - 1] : "",
    oldest: dated.length ? dated[0] : "",
  };
}

function quantile(sorted, q) {
  if (!sorted.length) return null;
  const index = Math.min(sorted.length - 1, Math.floor(q * sorted.length));
  return sorted[index];
}
