"""
Esri Careers API Scraper
Fetches jobs from Esri's Greenhouse ATS API
"""
import logging
from typing import Dict, List, Optional

import requests

from .models import JobPosting

logger = logging.getLogger(__name__)

ESRI_API_URL = "https://boards-api.greenhouse.io/v1/boards/esri/jobs"

def scrape_esri_jobs(
    allowed_countries: Optional[List[str]] = None,
    country_name_mapping: Optional[Dict[str, str]] = None
) -> List[JobPosting]:
    """Scrape jobs from Esri Greenhouse API."""
    from ..utils.country_utils import is_allowed_country

    logger.info("Fetching Esri jobs from Greenhouse API...")
    """
    Scrape jobs from Esri Greenhouse API.

    Returns:
        List of JobPosting objects
    """
    logger.info("Fetching Esri jobs from Greenhouse API...")

    try:
        response = requests.get(ESRI_API_URL, timeout=30)
        response.raise_for_status()
        data = response.json()

        all_jobs = data.get("jobs", [])
        logger.info(f"Total jobs from API: {len(all_jobs)}")

        # Handle both formats: list of jobs, or grouped by department
        job_postings = []
        for item in all_jobs:
            # First try to check if it's a job object directly
            if isinstance(item, dict):
                if "title" in item and "location" in item:
                    # Direct job object
                    jobs_in_dept = [item]
                elif "jobs" in item:
                    # Grouped by department
                    jobs_in_dept = item.get("jobs", [])
                else:
                    continue
            else:
                continue

            for job in jobs_in_dept:
                job_id = job.get("id", "")
                title = job.get("title", "Unknown")
                location = _format_location(job.get("location", {}))

                # Filter by allowed countries
                if allowed_countries:
                    if not is_allowed_country(location, allowed_countries):
                        logger.debug(f"Skipping Esri job in {location} (not in allowed countries)")
                        continue

                # Build URL
                abs_url = job.get("absolute_url", "")
                if not abs_url and job_id:
                    abs_url = f"https://esri.wd5.myworkdayjobs.com/en-US/External_Career_Site/job/{job_id}"

                # Extract description (may need to fetch detail page)
                description = job.get("content", "") or job.get("description", "")

                posting = JobPosting(
                    id=f"esri-{job_id}",
                    title=title,
                    company="Esri",
                    location=location,
                    description=description[:500] if description else "",
                    url=abs_url,
                    site="esri",
                    job_type=None,
                    remote=_check_remote(title, description),
                )
                job_postings.append(posting)

        logger.info(f"Successfully created {len(job_postings)} Esri job postings")
        return job_postings

    except Exception as e:
        logger.error(f"Failed to scrape Esri jobs: {e}")
        return []


def _format_location(location_data: dict) -> str:
    """Format Greenhouse location data."""
    if isinstance(location_data, dict):
        name = location_data.get("name", "")
        city = location_data.get("city", "")
        state = location_data.get("state", "")
        country = location_data.get("country", "")

        parts = [p for p in [city, state, country] if p]
        return ", ".join(parts) if parts else name
    return str(location_data) if location_data else "Unknown"


def _check_remote(title: str, description: str) -> str:
    """Check if job is remote."""
    text = (title + " " + description).lower()
    if "remote" in text or "telecommute" in text or "work from home" in text:
        return "Yes"
    return None
