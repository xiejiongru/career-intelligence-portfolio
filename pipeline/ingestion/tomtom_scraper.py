"""
TomTom Careers API Scraper
Fetches jobs directly from TomTom's internal API
"""
import logging
from typing import Dict, List, Optional

import requests

from .models import JobPosting

logger = logging.getLogger(__name__)

TOMTOM_API_URL = "https://www.tomtom.com/api/careers/jobs/"

def scrape_tomtom_jobs(
    category: str = "engineering",
    allowed_countries: Optional[List[str]] = None,
    country_name_mapping: Optional[Dict[str, str]] = None
) -> List[JobPosting]:
    """Scrape jobs from TomTom Careers API."""
    from ..utils.country_utils import is_allowed_country

    logger.info("Fetching TomTom jobs from API...")
    """
    Scrape jobs from TomTom Careers API.

    Args:
        category: Job category to filter (e.g., 'engineering', 'business-services')

    Returns:
        List of JobPosting objects
    """
    logger.info("Fetching TomTom jobs from API...")

    try:
        response = requests.get(TOMTOM_API_URL, timeout=30)
        response.raise_for_status()
        data = response.json()

        all_jobs = data.get("jobs", [])
        logger.info(f"Total jobs from API: {len(all_jobs)}")

        # Filter by category if specified
        if category:
            filtered_jobs = [
                job for job in all_jobs
                if category.lower() in job.get("category", "").lower()
                or category.lower() in job.get("team", "").lower()
                or category.lower() in job.get("title", "").lower()
            ]
            logger.info(f"Filtered to {len(filtered_jobs)} '{category}' jobs")
        else:
            filtered_jobs = all_jobs

        # Convert to JobPosting objects
        job_postings = []
        for job in filtered_jobs:
            location = job.get("location", "Unknown")

            # Filter by allowed countries
            if allowed_countries:
                if not is_allowed_country(location, allowed_countries):
                    logger.debug(f"Skipping TomTom job in {location} (not in allowed countries)")
                    continue

            # Build full URL
            slug = job.get("slug", "")
            job_url = f"https://www.tomtom.com/careers/job/{slug}/" if slug else TOMTOM_API_URL

            # Extract description text
            description = job.get("description", {})
            desc_text = ""
            if isinstance(description, dict):
                desc_text = " ".join([
                    section.get("body", "")
                    for section in description.get("sections", [])
                ])

            # Create JobPosting
            posting = JobPosting(
                id=f"tomtom-{job.get('jobId', '')}",
                title=job.get("title", "Unknown"),
                company="TomTom",
                location=job.get("location", "Unknown"),
                description=desc_text or job.get("team", ""),
                url=job_url,
                site="tomtom",
                job_type=job.get("commitment", None),
                remote=_map_workplace_type(job.get("workplaceType", "")),
            )
            job_postings.append(posting)

        logger.info(f"Successfully created {len(job_postings)} TomTom job postings")
        return job_postings

    except Exception as e:
        logger.error(f"Failed to scrape TomTom jobs: {e}")
        return []


def _map_workplace_type(workplace_type: str) -> str:
    """Map TomTom workplace type to remote field."""
    mapping = {
        "remote": "Yes",
        "hybrid": "Partial",
        "onsite": "No",
    }
    return mapping.get(workplace_type.lower() if workplace_type else "", None)
