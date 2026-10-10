import logging
import re
from typing import Any, Dict, List, Set

from ..ingestion.models import JobPosting
from ..utils.nlp import detect_language, process_text

logger = logging.getLogger(__name__)

class FranceGeoJobScreener:
    """
    用于筛选法国 GIS / Data / DevOps 岗位。
    执行：硬性排除 -> 结构化提取 -> 评分 -> 差距分析 -> 最终决策。
    """

    # 🚫 1. HARD EXCLUSION RULES
    EXCLUDE_KEYWORDS_TITLE = [
        "Embedded", "System Engineer", "Senior", "Manager", "Management",
        "ML Ops", "MLOps", "Android", "iOS", "Kotlin", "SysOps",
        "Infrastructure Engineer", "Kubernetes", "Algorithm Engineer",
        "Product Manager", "Product Owner", "Data Scientist",
        "Cyber Security", "Security Engineer", "Virtualization Engineer",
        "Linux Engineer", ".NET", "Integration Validation Engineer",
        "Qt", "C developer", "Hardware", "Private Cloud", "VMware"
    ]

    EXCLUDE_LANGUAGES = ["rust", "golang", "java", "c#", "pure c"]
    EXCLUDE_TOOLS = ["jenkins"] # Soft reject logic handled in code
    EXCLUDE_INDUSTRIES = ["defense", "military", "weapons", "intelligence", "banking"]

    # 🧠 2. EXTRACTION & NORMALIZATION
    SKILL_GROUPS = {
        "gis": ["sig", "géomatique", "cartographie", "spatial analysis", "qgis", "arcgis", "postgis", "fme"],
        "data": ["sql", "python", "r", "etl", "postgresql", "pandas", "data engineering"],
        "devops": ["docker", "ci/cd", "aws", "gcp", "automation", "scripting", "terraform"],
        "programming": ["python", "javascript", "typescript", "bash", "sql"]
    }

    # ⚖️ 3. SCORING MODEL
    WEIGHTS = {
        "tech_match": 0.35,
        "function_match": 0.20,
        "domain_match": 0.15,
        "experience_match": 0.15,
        "growth_potential": 0.15
    }

    def __init__(self, user_skills: Set[str]):
        self.user_skills = {s.lower() for s in user_skills}

    def screen(self, job: JobPosting) -> Dict[str, Any]:
        """
        全流程筛选入口
        """
        text = job.description
        title = job.title
        lang = detect_language(text)
        doc = process_text(text, lang=lang)

        # --- Stage 1: Filter Out ---
        filtered, filter_reasons = self._check_exclusions(title, text)

        # --- Stage 2: Extract Structure ---
        structure = self._extract_structure(title, text, doc)

        # --- Stage 3: Scoring ---
        scores = self._calculate_scores(structure, job)
        total_score = sum(scores.values())

        # --- Stage 4: Gap Analysis ---
        gap = self._analyze_gap(structure)

        # --- Stage 5: Decision ---
        decision = "skip"
        if not filtered:
            if total_score >= 80:
                decision = "apply"
            elif total_score >= 60:
                decision = "maybe"

        # Summary Generation
        summary = self._generate_summary(structure, total_score, gap, decision)

        return {
            "decision": decision,
            "score": round(total_score, 1),
            "filtered": filtered,
            "filter_reasons": filter_reasons,
            "job": {
                "title": title,
                "company": job.company,
                "location": [job.location] if job.location else []
            },
            "match_scores": {k: round(v, 1) for k, v in scores.items()},
            "skills": structure["skills"],
            "responsibilities": structure["responsibilities"],
            "seniority": structure["seniority"],
            "gap_analysis": gap,
            "summary": summary
        }

    def _check_exclusions(self, title: str, description: str) -> (bool, List[str]):
        reasons = []
        title_lower = title.lower()
        desc_lower = description.lower()

        # 标题排除
        for kw in self.EXCLUDE_KEYWORDS_TITLE:
            if kw.lower() in title_lower:
                reasons.append(f"Title contains excluded keyword: {kw}")

        # Linux in title exclude
        if "linux" in title_lower:
            reasons.append("Linux in title (Special exclusion rule)")

        # 语言排除
        for lang in self.EXCLUDE_LANGUAGES:
            if re.search(rf'\b{re.escape(lang)}\b', desc_lower):
                reasons.append(f"Description mentions excluded language: {lang}")

        # 行业排除
        for ind in self.EXCLUDE_INDUSTRIES:
            if ind in desc_lower:
                # Special exception for consulting
                if "consulting" in desc_lower or "conseil" in desc_lower or "prestation" in desc_lower:
                    continue
                reasons.append(f"Potentially excluded industry: {ind}")

        # Jenkins soft reject (only if major tool)
        if "jenkins" in desc_lower and desc_lower.count("jenkins") > 2:
             reasons.append("Major usage of Jenkins detected (Soft reject)")

        return len(reasons) > 0, reasons

    def _extract_structure(self, title: str, description: str, doc) -> Dict[str, Any]:
        desc_lower = description.lower()

        # 提取技能并归一化
        skills = {cat: [] for cat in self.SKILL_GROUPS}
        for cat, kws in self.SKILL_GROUPS.items():
            for kw in kws:
                if re.search(rf'\b{re.escape(kw)}\b', desc_lower):
                    skills[cat].append(kw.upper() if len(kw) < 5 else kw.capitalize())

        # 职责分类
        responsibilities = []
        resp_map = {
            "project_management": ["projet", "coordination", "management"],
            "data_engineering": ["pipeline", "etl", "flux", "données", "data"],
            "gis_analysis": ["analyse spatiale", "cartographie", "sig", "gis"],
            "visualization": ["visualisation", "dashboard", "restitution"],
            "consulting": ["conseil", "accompagnement", "client"],
            "business_development": ["commercial", "développement", "vente"]
        }
        for cat, kws in resp_map.items():
            if any(kw in desc_lower for kw in kws):
                responsibilities.append(cat)

        # 职级判定
        seniority = "Junior/Intermediate"
        if any(kw in desc_lower for kw in ["confirmé", "expérimenté", "senior"]):
            seniority = "Senior"

        return {
            "skills": {k: list(set(v)) for k, v in skills.items()},
            "responsibilities": list(set(responsibilities)),
            "seniority": seniority
        }

    def _calculate_scores(self, structure: Dict[str, Any], job: JobPosting) -> Dict[str, float]:
        scores = {}

        # 1. Tech Match (35%)
        found_techs = set()
        for s_list in structure["skills"].values():
            for s in s_list:
                found_techs.add(s.lower())

        overlap = found_techs.intersection(self.user_skills)
        tech_score = (len(overlap) / max(len(found_techs), 1)) * 35
        scores["tech_match"] = tech_score

        # 2. Function Match (20%)
        # Priority: GIS + Data overlap
        func_score = 0
        resps = structure["responsibilities"]
        if "gis_analysis" in resps and "data_engineering" in resps:
            func_score = 20
        elif "gis_analysis" in resps or "data_engineering" in resps:
            func_score = 15
        else:
            func_score = 10
        scores["function_match"] = func_score

        # 3. Domain Match (15%)
        domain_score = 0
        desc_lower = job.description.lower()
        high_domains = ["sig", "gis", "urbanisme", "public", "collectivité", "conseil"]
        if any(d in desc_lower for d in high_domains):
            domain_score = 15
        elif "data" in desc_lower:
            domain_score = 10
        else:
            domain_score = 5
        scores["domain_match"] = domain_score

        # 4. Experience Match (15%)
        # Placeholder: assume match for now as extraction is hard without LLM
        scores["experience_match"] = 12

        # 5. Growth Potential (15%)
        # Leverage geo-data pipelines / automation
        growth_score = 5
        if "automation" in desc_lower or "scripting" in desc_lower or "pipeline" in desc_lower:
            growth_score = 15
        scores["growth_potential"] = growth_score

        return scores

    def _analyze_gap(self, structure: Dict[str, Any]) -> Dict[str, List[str]]:
        missing = []
        risks = []
        leverage = []

        found_techs = set()
        for s_list in structure["skills"].values():
            for s in s_list:
                found_techs.add(s.lower())

        # Missing core skills
        for tech in found_techs:
            if tech not in self.user_skills:
                missing.append(tech.capitalize())

        # Risks
        if structure["seniority"] == "Senior":
            risks.append("Role might require more seniority than current trajectory")
        if "devops" in structure["skills"] and len(structure["skills"]["devops"]) > 3:
            risks.append("Heavy DevOps focus might be outside core GIS/Data interest")

        # Leverage points
        if "gis" in structure["skills"] and "data" in structure["skills"]:
            leverage.append("Strong overlap between GIS and Data Engineering")
        if "automation" in str(structure["skills"]):
            leverage.append("Good opportunity to leverage scripting/automation skills")

        return {
            "missing_skills": list(set(missing))[:5],
            "risk_factors": risks,
            "leverage_points": leverage
        }

    def _generate_summary(self, structure, total_score, gap, decision) -> str:
        role_type = "GIS/Data" if "gis_analysis" in structure["responsibilities"] else "General Technical"
        if decision == "apply":
            suitability = "highly suitable"
        elif decision == "maybe":
            suitability = "potentially suitable"
        else:
            suitability = "not recommended"

        risk_msg = f" Main risk: {gap['risk_factors'][0]}." if gap['risk_factors'] else ""

        return (
            f"This is a {role_type} role with a {structure['seniority']} level. "
            f"The match quality is {suitability} (Score: {round(total_score, 1)})."
            f"{risk_msg} It aligns well with your focus on geo-data pipelines."
        )
