"""Schneider Electric Job Scraper - Uses direct API like TomTom/Esri."""

import logging
from typing import Dict, List, Optional

import requests

from .models import JobPosting

logger = logging.getLogger(__name__)

SCHNEIDER_API_URL = "https://careers-api.se.com/v1/jobs"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
}


def _matches_allowed_countries(
    country: str,
    allowed_countries: List[str],
    country_name_mapping: Optional[Dict[str, str]] = None
) -> bool:
    """Check if country matches any of the allowed countries (case-insensitive)."""
    if not allowed_countries:
        return True  # No filter means accept all

    country_lower = country.lower()

    # Direct match
    if any(ac.lower() in country_lower or country_lower in ac.lower() for ac in allowed_countries):
        return True

    # Use country name mapping if provided
    if country_name_mapping:
        for native_name, english_name in country_name_mapping.items():
            if native_name in country:
                # Check if the English mapped name is in allowed list
                if any(english_name.lower() in ac.lower() or ac.lower() in english_name.lower()
                       for ac in allowed_countries):
                    return True

    return False


def scrape_schneider_jobs(
    max_jobs: int = 20,
    allowed_countries: Optional[List[str]] = None,
    country_name_mapping: Optional[Dict[str, str]] = None
) -> List[JobPosting]:
    """
    Scrape Schneider Electric job postings using their REST API.

    Args:
        max_jobs: Maximum number of jobs to return (default: 20)
        allowed_countries: List of allowed countries from config.yaml.
                          If None, accepts all countries.
        country_name_mapping: Dictionary mapping non-English country names to English.
                             Loaded from config.yaml's country_name_mapping.

    Returns:
        List of JobPosting objects
    """
    logger.info("Starting Schneider Electric job scraping via API...")

    if allowed_countries:
        logger.info(f"Filtering by countries: {allowed_countries}")

    try:
        response = requests.get(SCHNEIDER_API_URL, headers=HEADERS, timeout=30)
        response.raise_for_status()

        # Force UTF-8 encoding to handle international characters correctly
        response.encoding = 'utf-8'

        data = response.json()
        all_jobs_raw = data.get('jobs', [])

        logger.info(f"API returned {len(all_jobs_raw)} total jobs")

        # Filter and transform jobs
        all_jobs = []
        for job_raw in all_jobs_raw:
            if len(all_jobs) >= max_jobs:
                break

            job_data = job_raw.get('data', {})

            # Extract location info (direct fields, not nested)
            country = job_data.get('country', '')
            city = job_data.get('city', '')
            state = job_data.get('state', '')
            full_location = job_data.get('full_location', '')

            # Filter by allowed countries
            if not _matches_allowed_countries(country, allowed_countries, country_name_mapping):
                logger.debug(f"  Skipping job in {country} (not in allowed list)")
                continue

            # Build location string
            location = full_location or ' / '.join([p for p in [city, state, country] if p])

            # Extract job details
            title = job_data.get('title', 'Unknown')
            description = job_data.get('description', '')
            slug = job_data.get('slug', '')
            req_id = job_data.get('req_id', '')

            # Build job URL
            job_url = f"https://careers.se.com/jobs/{slug}" if slug else SCHNEIDER_API_URL

            # Extract posted date
            date_posted = job_data.get('posted_date')

            # Create JobPosting object
            job = JobPosting(
                id=f"schneider-{req_id or slug}",
                title=title,
                company='Schneider Electric',
                location=location or country,
                description=description[:2000] if description else '',
                url=job_url,
                site='schneider_electric',
                date_posted=date_posted,
            )

            all_jobs.append(job)
            logger.info(f"  ✓ Parsed: {title[:60]} | {location}")

        logger.info(f"Successfully scraped {len(all_jobs)} jobs from Schneider Electric")
        return all_jobs

    except Exception as e:
        logger.error(f"Failed to scrape Schneider Electric jobs: {e}")
        return []


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    max_jobs = int(sys.argv[1]) if len(sys.argv) > 1 else 10

    jobs = scrape_schneider_jobs(max_jobs=max_jobs)

    print(f"\nTotal jobs scraped: {len(jobs)}")
    print("\nSample jobs:")
    for i, job in enumerate(jobs[:3], 1):
        print(f"\n{i}. {job.title}")
        print(f"   Location: {job.location}")
        print(f"   Type: {job.job_type}")
        print(f"   URL: {job.url}")
