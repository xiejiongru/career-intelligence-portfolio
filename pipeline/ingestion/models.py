from dataclasses import dataclass, field
from typing import List, Optional

import yaml


@dataclass
class JobPosting:
    id: str
    title: str
    company: str
    location: str
    description: str
    url: str
    site: str
    job_type: Optional[str] = None
    salary: Optional[str] = None
    date_posted: Optional[str] = None
    experience: Optional[str] = None
    education: Optional[str] = None
    remote: Optional[str] = None

    final_score: float = 0.0
    reason: str = ""
    missing_skills: List[str] = field(default_factory=list)
    passed_hard_filter: bool = True
    thinking_trace: str = ""


def validate_job_posting(job: JobPosting) -> List[str]:
    errors = []
    if not job.title or not job.title.strip():
        errors.append(f"job {job.id}: title is empty")
    if not job.url or not job.url.strip():
        errors.append(f"job {job.id}: url is empty")
    if not job.site or not job.site.strip():
        errors.append(f"job {job.id}: site is empty")
    if job.final_score < 0.0 or job.final_score > 100.0:
        errors.append(f"job {job.id}: final_score {job.final_score} out of [0, 100]")
    return errors


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def print_config_audit(config: dict):
    search = config.get("search", {})
    ranking = config.get("ranking", {})
    pipeline = config.get("pipeline", {})
    hard_filter = config.get("hard_filter", {})
    ats = ranking.get("ats_companies", {})

    audit_lines = [
        "=== Pipeline Config ===",
        f"  mode: {pipeline.get('global_mode', False) and 'global' or 'france'}",
        f"  top_n: {pipeline.get('top_n', '?')}",
        f"  keywords: {len(search.get('keywords', []))} total",
        f"  sources: jobspy({search.get('sites', [])}), georezo, platform({len(search.get('custom_urls', []))} urls)",
        f"  target_skills: {len(ranking.get('target_skills', []))} total",
        f"  ats_companies: greenhouse({len(ats.get('greenhouse', []))})"
        f" + lever({len(ats.get('lever', []))})"
        f" + smartrecruiters({len(ats.get('smartrecruiters', []))})",
        f"  allowed_countries: {len(search.get('allowed_countries', []))}",
        f"  allowed_job_types: {hard_filter.get('allowed_job_types', [])}",
        f"  llm: {config.get('llm', {}).get('model', '?')} @ {config.get('llm', {}).get('base_url', '?')}",
        "=========================",
    ]
    for line in audit_lines:
        print(line)
