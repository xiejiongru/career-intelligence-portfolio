"""
Job Deduplication
"""
import hashlib

from rapidfuzz import fuzz


def create_job_key(job: dict) -> str:
    """Create unique key for a job (for dedup)"""
    title = (job.get('title', '') or '').lower().strip()
    company = (job.get('company', '') or '').lower().strip()
    location = (job.get('location', '') or '').lower().strip()

    key_string = f"{title}|{company}|{location}"
    return hashlib.md5(key_string.encode()).hexdigest()[:12]


def is_duplicate(job_a: dict, job_b: dict, threshold: float = 85.0) -> bool:
    """Check if two jobs are duplicates using fuzzy matching"""
    title_a = job_a.get('title', '') or ''
    title_b = job_b.get('title', '') or ''
    company_a = job_a.get('company', '') or ''
    company_b = job_b.get('company', '') or ''

    title_ratio = fuzz.ratio(title_a.lower(), title_b.lower())
    company_match = fuzz.ratio(company_a.lower(), company_b.lower())

    return title_ratio > threshold and company_match > threshold


def deduplicate_jobs(jobs: list, threshold: float = 85.0) -> list:
    """Remove duplicate jobs"""
    seen_keys = set()
    unique_jobs = []

    for job in jobs:
        key = create_job_key(job)
        if key not in seen_keys:
            seen_keys.add(key)
            unique_jobs.append(job)

    return unique_jobs
