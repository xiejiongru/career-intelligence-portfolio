"""
Capgemini scraper - uses their JobStream API
"""
import logging
from typing import List, Optional

import requests

from .models import JobPosting

logger = logging.getLogger(__name__)

API_BASE = "https://cg-jobstream-api.azurewebsites.net/api"

def scrape(filters: Optional[dict] = None, max_jobs: int = 30) -> List[JobPosting]:
    """Scrape Capgemini jobs via JobStream API"""
    logger.info("Scraping Capgemini...")

    all_jobs = []
    page = 1
    page_size = min(max_jobs, 100)

    params = {
        'page': page,
        'size': page_size,
        'country_code': 'fr-fr',
    }

    if filters:
        params.update(filters)

    try:
        r = requests.get(f"{API_BASE}/job-search", params=params, timeout=30)
        data = r.json()

        total = data.get('total', 0)
        jobs = data.get('data', [])
        logger.info(f"Found {total} Capgemini jobs")

        seen = set()
        count = 0

        for job in jobs:
            if count >= max_jobs:
                break

            title = (job.get('title') or '').strip()
            if not title or title in seen:
                continue
            seen.add(title)

            company = job.get('brand', 'Capgemini') or 'Capgemini'
            location_str = job.get('location', 'France')
            url = job.get('apply_job_url', '') or ''

            # Build a richer description
            parts = []
            if job.get('contract_type'):
                parts.append(f"Contract: {job['contract_type']}")
            if job.get('experience_level'):
                parts.append(f"Experience: {job['experience_level']}")
            if job.get('professional_communities'):
                pc = job['professional_communities']
                if isinstance(pc, list):
                    parts.append(f"Domain: {', '.join(pc)}")
            description = ' | '.join(parts) if parts else 'Job from Capgemini'

            posting = JobPosting(
                id=f"capgemini-{count}",
                title=title[:200],
                company=company[:100],
                location=location_str,
                description=description,
                url=url,
                site="capgemini"
            )
            all_jobs.append(posting)
            count += 1

    except Exception as e:
        logger.error(f"Capgemini API error: {e}")

    logger.info(f"Created {len(all_jobs)} Capgemini jobs")
    return all_jobs
