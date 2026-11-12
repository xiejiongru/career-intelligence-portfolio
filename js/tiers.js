// Score tiers: the single place that defines what "worth applying" means on the dashboard.
//
// Why the tier is not just a score band: the pipeline's final_score measures keyword
// relevance, while decision records the hard gates (seniority, degree, deadline, ...).
// In the 2026-11-09 snapshot 12 of the 13 highest-scoring rows were `skip`, e.g. an
// "Architecte Géospatial" that requires 8+ years scoring 68.8. Colouring by score alone
// would paint those the greenest, so a row is only "must apply" when it both cleared the
// gates (decision = apply) and scored well.
//
// Thresholds are calibrated against human labels, not against the score distribution.
// eval/labels/jobs-2026-11-06-annotated.csv carries 644 hand-judged rows (9 必投,
// 14 有时间再投). Joining them onto the 2026-11-09 snapshot:
//
//   cut 35 -> green band holds 35 rows, but only 35% of the labelled ones are worth
//             applying (12 of 20 are 不投). 16 apply rows sit at exactly 36.8 and 9 of
//             the 10 labelled ones there are 不投, so the band was mostly noise.
//   cut 38 -> 19 rows; precision rises to 60% (P(必投) 40%). The >=38 band vs the
//             [35,38) band is measurably different (10 rows, 6 positives vs 9 rows,
//             1 positive); see tests/unit/test_dashboard_tiers.py for the labelled
//             evidence. It still keeps the SDIS78 "Chef de Projet Géomatique" (38.8)
//             that a human called 必投.
//
// `maybe` = 28 keeps green+amber at 45 of 1246 rows (3.6%), matching the 3.6% rate of
// worthwhile postings in the labelled sample; a cut of 20 made it 76 rows (6.1%).
// Both cuts land in a gap of the score scale (26.1|28.1 and 36.8|38.8), so a re-scored
// run does not slide rows across a boundary.
//
// This is still the legacy keyword score, not the rubric score of
// docs/research/06 §4.1 (>=65 必投 / 45-64 有时间再投 over five weighted components).
// The pipeline does not emit that score yet - all five score_*_match columns are 0 -
// and the two scales correlate at only Spearman 0.137, so these numbers are a
// placeholder, not the rubric. Change them here; nothing else hard-codes a number.

export const SCORE_THRESHOLDS = { must: 38, maybe: 28 };

export const TIERS = [
  { id: "must", label: "必投", rule: `通过全部闸门（decision=apply）且评分 ≥ ${SCORE_THRESHOLDS.must}` },
  { id: "maybe", label: "有时间再投", rule: `通过全部闸门且评分 ${SCORE_THRESHOLDS.maybe}–${SCORE_THRESHOLDS.must}` },
  { id: "review", label: "待复核", rule: "信息不足（多半是没抓到 JD），分数不可信，先人工看一眼" },
  { id: "low", label: "低分", rule: `通过闸门，但评分 < ${SCORE_THRESHOLDS.maybe}` },
  { id: "blocked", label: "被拦截", rule: "被硬过滤或硬闸门（资历/学历/截止/方向…）拦下；分数仅供参考" },
];

const TIER_INDEX = Object.fromEntries(TIERS.map((tier, index) => [tier.id, index]));

export function tierOf(row) {
  const score = Number(row.final_score);
  const value = Number.isFinite(score) ? score : 0;
  if (row.decision === "apply") {
    if (value >= SCORE_THRESHOLDS.must) return "must";
    if (value >= SCORE_THRESHOLDS.maybe) return "maybe";
    return "low";
  }
  if (row.decision === "needs_review") return "review";
  return "blocked";
}

// Higher is better. Closed postings sink below everything: they cannot be applied to.
export function priorityOf(row, tier) {
  const score = Number(row.final_score) || 0;
  if (row.status === "closed") return score - 1000;
  return (TIERS.length - 1 - TIER_INDEX[tier]) * 1000 + score;
}

const GATES = {
  G0_deadline: "已截止",
  G0_nationality: "国籍限制",
  G0_sector: "行业排除",
  G1_location: "地点不符",
  G2_seniority: "资历要求",
  G3_degree: "学历要求",
  G4_profession: "方向不符",
  insufficient_data: "无可用 JD",
};

function hardLabel(code) {
  if (code === "salary_below_floor") return "薪资过低";
  if (code === "country_not_allowed") return "国家不符";
  if (code.startsWith("exclude_keyword:")) return `排除词 ${code.slice("exclude_keyword:".length)}`;
  if (code.startsWith("job_type_not_allowed:")) return `合同 ${code.slice("job_type_not_allowed:".length)}`;
  if (code.startsWith("missing_mandatory_skill:")) return `缺少必备技能 ${code.slice("missing_mandatory_skill:".length)}`;
  return code;
}

// Short human label for why a row was blocked / needs review. Empty for rows that passed.
export function gateOf(row, tier) {
  if (tier !== "blocked" && tier !== "review") return "";
  const code = String(row.filter_reasons || "").split(":")[0].trim();
  if (GATES[code]) return GATES[code];
  const hard = String(row.hard_filter_reasons || "").split(/[;|,]/)[0].trim();
  if (hard) return hardLabel(hard);
  return code;
}
