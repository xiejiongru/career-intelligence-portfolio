"""
Thinking Kernel: multi-role critique loop for decision augmentation.

Each job passes through 4 thinking layers in sequence.
Each layer MUST challenge the previous one.
Final output is synthesis, not repetition.

Framework:
  Input → System Layer → Human Layer → Validation Layer → Critique Layer → Score
"""
import logging
from dataclasses import dataclass, field
from typing import List

from pipeline.ingestion.models import JobPosting

logger = logging.getLogger(__name__)


@dataclass
class Adjustment:
    layer: str
    delta: float
    reason: str
    confidence: str  # high / medium / low

    def short(self) -> str:
        sign = "+" if self.delta >= 0 else ""
        return f"[{self.layer}|{self.confidence}] {sign}{self.delta}: {self.reason}"


@dataclass
class ThinkingResult:
    job_id: str
    title: str
    baseline_score: float
    adjustments: List[Adjustment] = field(default_factory=list)
    final_score: float = 0.0

    @property
    def trace(self) -> str:
        lines = [f"  baseline: {self.baseline_score}"]
        for a in self.adjustments:
            lines.append(f"  {a.short()}")
        lines.append(f"  final: {self.final_score}")
        return "\n".join(lines)


class ThinkingKernel:
    """4-layer critique loop for job scoring."""

    # Companies whose core business IS geospatial / GIS / mapping
    GIS_COMPANIES = {
        "tomtom", "esri", "here technologies", "here", "magellium",
        "ign", "cnes", "airbus defence", "airbusDS", "thales",
        "alstom", "systra", "sncf", "ingenieus",
    }

    def evaluate(self, job: JobPosting, context: dict) -> ThinkingResult:
        baseline = self._baseline_score(job, context)
        result = ThinkingResult(
            job_id=job.id,
            title=job.title,
            baseline_score=baseline,
        )

        # Layer 1: System — structural soundness of the match
        result.adjustments.extend(self._system_layer(job, context, baseline))
        current = baseline + sum(a.delta for a in result.adjustments)

        # Layer 2: Human — cognitive fit, UX of the role
        result.adjustments.extend(self._human_layer(job, context, current))
        current = baseline + sum(a.delta for a in result.adjustments)

        # Layer 3: Validation — measurability, data quality
        result.adjustments.extend(self._validation_layer(job, context, current))
        current = baseline + sum(a.delta for a in result.adjustments)

        # Layer 4: Critique — challenge assumptions, find failure modes
        result.adjustments.extend(self._critique_layer(job, context, current))
        current = baseline + sum(a.delta for a in result.adjustments)

        result.final_score = max(0.0, min(100.0, current))
        return result

    # ------------------------------------------------------------------
    # Baseline: existing keyword-match score normalized to 0-100
    # ------------------------------------------------------------------
    def _baseline_score(self, job: JobPosting, ctx: dict) -> float:
        target_skills = ctx.get("target_skills", [])
        if not target_skills:
            return 50.0

        text = f"{job.title} {job.description}".lower()
        matched = sum(1 for s in target_skills if s.lower() in text)
        return round(matched / len(target_skills) * 100, 1)

    # ------------------------------------------------------------------
    # Layer 1: System — architecture, constraints, scalability
    # ------------------------------------------------------------------
    def _system_layer(self, job: JobPosting, ctx: dict, score: float) -> List[Adjustment]:
        result = []

        # Company domain bonus — GIS/mapping companies are inherently relevant
        company_lower = (job.company or "").lower()
        if company_lower in self.GIS_COMPANIES:
            result.append(Adjustment("system", 15, f"GIS/mapping company: {job.company}", "high"))

        # Skill coverage breadth
        target_skills = ctx.get("target_skills", [])
        text = f"{job.title} {job.description}".lower()
        matched = [s for s in target_skills if s.lower() in text]

        if len(matched) >= 4:
            result.append(Adjustment("system", 5, "broad skill coverage (4+)", "high"))
        elif len(matched) <= 1:
            result.append(Adjustment("system", -5, "narrow skill coverage (<=1)", "medium"))

        # Seniority signal — titles with "senior" / "lead" / "architect"
        title_lower = job.title.lower()
        senior_signals = ["senior", "lead", "architect", "staff", "principal", "manager"]
        has_senior = any(s in title_lower for s in senior_signals)
        junior_signals = ["junior", "intern", "trainee", "apprentice"]
        has_junior = any(s in title_lower for s in junior_signals)

        if has_senior and score > 40:
            result.append(Adjustment("system", 3, "senior-level role aligns with experience", "medium"))
        if has_junior:
            result.append(Adjustment("system", -10, "junior-level role may underutilize skills", "medium"))

        return result

    # ------------------------------------------------------------------
    # Layer 2: Human — cognitive fit, UX of the role
    # ------------------------------------------------------------------
    def _human_layer(self, job: JobPosting, ctx: dict, score: float) -> List[Adjustment]:
        result = []

        text = f"{job.title} {job.description}".lower()
        ctx.get("preferred_technologies", [])

        # Domain alignment bonus
        domain_keywords = ctx.get("domain_keywords", [])
        domain_matches = sum(1 for d in domain_keywords if d.lower() in text)
        if domain_matches >= 2:
            result.append(Adjustment("human", 4, "strong domain alignment", "high"))
        elif domain_matches == 0:
            result.append(Adjustment("human", -2, "no domain keywords in description", "low"))

        # Location realism
        if job.location and job.location != "Unknown":
            allowed = ctx.get("allowed_locations", [])
            if allowed:
                in_area = any(loc.lower() in job.location.lower() for loc in allowed)
                if in_area:
                    result.append(Adjustment("human", 3, "preferred location match", "high"))
                else:
                    result.append(Adjustment("human", -3, "outside preferred locations", "medium"))

        return result

    # ------------------------------------------------------------------
    # Layer 3: Validation — data quality, measurability
    # ------------------------------------------------------------------
    def _validation_layer(self, job: JobPosting, ctx: dict, score: float) -> List[Adjustment]:
        result = []

        # Missing critical fields degrade confidence
        missing = []
        if not job.description or job.description in ("", "Job from ...", f"Job from {job.site}"):
            missing.append("description")
        if not job.url:
            missing.append("url")
        if not job.company or job.company == "Unknown":
            missing.append("company")

        if missing:
            result.append(Adjustment("validation", -5 * len(missing),
                                     f"missing fields: {', '.join(missing)}", "high"))

        # Salary signal
        if job.salary:
            result.append(Adjustment("validation", 2, "salary data available", "low"))

        return result

    # ------------------------------------------------------------------
    # Layer 4: Critique — challenge assumptions, find failure modes
    # ------------------------------------------------------------------
    def _critique_layer(self, job: JobPosting, ctx: dict, score: float) -> List[Adjustment]:
        result = []
        text = f"{job.title} {job.description}".lower()

        # Buzzword risk: title has hype but no substance in description
        buzzwords = ["ai", "machine learning", "deep learning", "blockchain", "metaverse"]
        has_buzz = any(b in text for b in buzzwords)
        target_skills = ctx.get("target_skills", [])
        has_real_skills = any(s.lower() in text for s in target_skills)

        if has_buzz and not has_real_skills:
            result.append(Adjustment("critique", -5, "buzzwords without substantiating skills", "medium"))

        # Over-qualification risk: too many skills required vs offered
        required_terms = ["must have", "required", "mandatory", "minimum"]
        requirement_count = sum(1 for t in required_terms if t in text)
        if requirement_count >= 3 and score < 30:
            result.append(Adjustment("critique", -3, "many hard requirements but low match", "medium"))

        # Company reputation / stability filter
        risky_terms = ["startup", "contract", "temporary", "freelance"]
        if any(t in text for t in risky_terms):
            result.append(Adjustment("critique", -2, "non-permanent role type flagged", "low"))

        return result
