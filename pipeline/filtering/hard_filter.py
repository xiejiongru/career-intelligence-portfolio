import re
from typing import Set

from ..ingestion.models import JobPosting
from ..utils.nlp import process_text


def get_known_technologies(config: dict) -> set:
    """从配置中获取已知技术列表"""
    tech_config = config.get("hard_filter", {}).get("known_technologies", {})
    if not tech_config:
        return set()

    all_techs = set()
    for category in tech_config.values():
        if isinstance(category, list):
            all_techs.update(t.lower() for t in category)
    return all_techs


def hard_filter(job: JobPosting, user_skills: Set[str], config: dict) -> JobPosting:
    """
    识别 JD 中的强制要求，对比用户技能，不满足则标记。
    使用 SpaCy 进行 Tokenization 以获得更准确的匹配。
    同时支持合同类型 (job_type) 过滤。
    """
    # 1. Exclude keywords (title-based)
    exclude_kws = config.get("ranking", {}).get("exclude_keywords", [])
    title_lower = job.title.lower() if job.title else ""
    for kw in exclude_kws:
        kw_lower = kw.lower()
        if len(kw_lower) <= 3:
            if re.search(r'\b' + re.escape(kw_lower) + r'\b', title_lower):
                job.passed_hard_filter = False
                return job
        else:
            if kw_lower in title_lower:
                job.passed_hard_filter = False
                return job

    # 1b. Exclude company patterns (defense/military)
    company_lower = (job.company or "").lower()
    exclude_company = config.get("hard_filter", {}).get("exclude_company_patterns", [])
    for pat in exclude_company:
        if pat.lower() in company_lower:
            job.passed_hard_filter = False
            return job

    # 2. 合同类型过滤
    allowed_types = config["hard_filter"].get("allowed_job_types", [])
    if allowed_types and job.job_type:
        if not any(t.upper() in job.job_type.upper() for t in allowed_types):
            job.passed_hard_filter = False
            return job

    # 2. 强制技能要求过滤
    mandatory_kws = config["hard_filter"]["mandatory_keywords"]
    known_techs = get_known_technologies(config)

    if not known_techs:
        return job

    doc = process_text(job.description)
    if not doc:
        return job

    for sent in doc.sents:
        sent_text = sent.text.lower()

        if any(kw.lower() in sent_text for kw in mandatory_kws):
            sent_tokens = {token.text.lower() for token in sent if not token.is_punct}

            for tech in known_techs:
                if tech in sent_tokens:
                    if tech not in user_skills:
                        job.passed_hard_filter = False
                        if tech not in job.missing_skills:
                            job.missing_skills.append(tech)

    return job
