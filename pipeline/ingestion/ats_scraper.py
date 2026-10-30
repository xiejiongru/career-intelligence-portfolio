"""
ATS Scraper - Greenhouse, Lever, SmartRecruiters
With FILTER at scrape time
"""
import logging
from typing import List

import requests

from ..utils.country_utils import is_allowed_country
from .models import JobPosting

logger = logging.getLogger(__name__)

# Pre-filter at scrape time - VERY lenient for global tech
FILTER = {
    "location": [
        "paris", "remote", "ile-de-france", "france", "london",
        "dublin", "berlin", "amsterdam", "europe",
    ],
    "keywords": [
        "devops", "sre", "cloud", "gis", "data", "geographic",
        "spatial", "mapping", "engineer", "software", "developer",
        "backend", "full stack", "platform", "infrastructure",
        "site reliability", "security",
    ],
    "exclude": [
        "senior staff", "principal ", "vp ", "director of",
        "chief ", "intern ", "manager,", "lead,",
        "senior engineer", "staff engineer",
    ],
}

def matches_filter(title: str, location: str) -> bool:
    """Check if job matches filter criteria"""
    title_lower = title.lower()
    loc_lower = location.lower()

    # Exclude very senior roles only (exact match)
    if title_lower.startswith("principal") or title_lower.startswith("vp ") or title_lower.startswith("chief"):
        return False

    # Must be in allowed location or remote (location is primary filter)
    has_location = any(loc in loc_lower for loc in FILTER["location"])
    if not has_location:
        return False

    # Must have at least one keyword (softer filter)
    has_keyword = any(kw in title_lower for kw in FILTER["keywords"])

    return has_keyword

def scrape_ats_jobs(
    ats_type: str = "greenhouse",
    companies: List[str] = None,
    allowed_countries: List[str] = None,
    max_jobs: int = 50
) -> List[JobPosting]:
    """Scrape jobs from ATS APIs"""
    logger.info(f"Scraping ATS jobs: {ats_type}")

    all_jobs = []

    if ats_type == "greenhouse":
        return scrape_greenhouse(companies, allowed_countries, max_jobs)
    elif ats_type == "lever":
        return scrape_lever(companies, allowed_countries, max_jobs)
    elif ats_type == "smartrecruiters":
        return scrape_smartrecruiters(companies, allowed_countries, max_jobs)

    return all_jobs

def scrape_greenhouse(companies, allowed_countries, max_jobs):
    all_jobs = []
    for company in companies:
        try:
            url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
            r = requests.get(url, timeout=15)
            if r.status_code != 200:
                continue

            data = r.json()
            jobs = data.get('jobs', [])
            logger.info(f"Greenhouse {company}: {len(jobs)} jobs")

            for job in jobs[:max_jobs // len(companies)]:
                location = job.get('location', {}).get('name', 'Remote')
                title = job.get('title', '')

                # Apply FILTER at scrape time
                if not matches_filter(title, location):
                    continue

                # Lenient filtering - accept any job with a valid location
                # (global tech companies often have remote/hybrid options)
                if not location or location.lower() in ['unknown', '', 'remote']:
                    location = 'Remote'

                j = JobPosting(
                    id=f"gh-{job.get('id')}",
                    title=job.get('title', '')[:200],
                    company=company.capitalize(),
                    location=location,
                    description=job.get('content', '')[:500] if job.get('content') else '',
                    url=job.get('absolute_url', ''),
                    site="greenhouse"
                )
                all_jobs.append(j)

        except Exception as e:
            logger.error(f"Greenhouse {company}: {e}")

    logger.info(f"Created {len(all_jobs)} Greenhouse job postings")
    return all_jobs

def scrape_lever(companies, allowed_countries, max_jobs):
    all_jobs = []
    for company in companies:
        try:
            url = f"https://api.lever.co/v0/postings/{company}?mode=json"
            r = requests.get(url, timeout=15)
            if r.status_code != 200:
                continue

            jobs = r.json()
            logger.info(f"Lever {company}: {len(jobs)} jobs")

            for job in jobs[:max_jobs // len(companies)]:
                categories = job.get('categories', {})
                location = categories.get('location', 'Remote')
                title = job.get('text', '')

                # Apply FILTER at scrape time
                if not matches_filter(title, location):
                    continue

                # Lenient filtering
                if not location or location.lower() in ['unknown', '', 'remote']:
                    location = 'Remote'

                j = JobPosting(
                    id=f"lever-{job.get('id')}",
                    title=job.get('text', '')[:200],
                    company=company.capitalize(),
                    location=location,
                    description=job.get('description', '')[:500] if job.get('description') else '',
                    url=job.get('hostedUrl', ''),
                    site="lever"
                )
                all_jobs.append(j)

        except Exception as e:
            logger.error(f"Lever {company}: {e}")

    logger.info(f"Created {len(all_jobs)} Lever job postings")
    return all_jobs

def scrape_smartrecruiters(companies, allowed_countries, max_jobs):
    all_jobs = []
    for company in companies:
        try:
            url = f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
            r = requests.get(url, timeout=15)
            if r.status_code != 200:
                continue

            data = r.json()
            jobs = data.get('content', [])
            logger.info(f"SmartRecruiters {company}: {len(jobs)} jobs")

            for job in jobs[:max_jobs // len(companies)]:
                location = job.get('location', {}).get('city', 'Remote')

                if allowed_countries and not is_allowed_country(location, allowed_countries):
                    continue

                j = JobPosting(
                    id=f"sr-{job.get('ref')}",
                    title=job.get('name', '')[:200],
                    company=company.capitalize(),
                    location=location,
                    description=job.get('description', '')[:500] if job.get('description') else '',
                    url=job.get('urls', {}).get('apply', ''),
                    site="smartrecruiters"
                )
                all_jobs.append(j)

        except Exception as e:
            logger.error(f"SmartRecruiters {company}: {e}")

    logger.info(f"Created {len(all_jobs)} SmartRecruiters job postings")
    return all_jobs
