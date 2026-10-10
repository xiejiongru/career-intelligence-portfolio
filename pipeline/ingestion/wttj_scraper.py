"""
WTTJ Scraper v2 - Multiple category pages
"""
import logging
import re
from typing import List

import requests

from ..utils.country_utils import is_allowed_country
from .models import JobPosting

logger = logging.getLogger(__name__)

# Multiple category pages to scrape
CATEGORY_PAGES = {
    'developpeur': 'https://www.welcometothejungle.com/fr/pages/emploi-developpeur',
    'informatique': 'https://www.welcometothejungle.com/fr/pages/emploi-informatique',
    'data': 'https://www.welcometothejungle.com/fr/pages/emploi-informatique',
    'chef-projet': 'https://www.welcometothejungle.com/fr/pages/emploi-chef-projet',
    'ingenieur': 'https://www.welcometothejungle.com/fr/pages/emploi-ingenieur',
    'iot': 'https://www.welcometothejungle.com/fr/pages/emploi-iot',
    'devops': 'https://www.welcometothejungle.com/fr/pages/emploi-developpeur',
    'geomaticien': 'https://www.welcometothejungle.com/fr/pages/emploi-developpeur',
}

def parse_wttj_job_slug(slug: str) -> dict:
    """Parse job slug to extract title, location, company"""
    parts = slug.rsplit('_', 1)
    if len(parts) == 2:
        location = parts[1]
        title_rest = parts[0].replace('-', ' ')
    else:
        location = 'France'
        title_rest = slug.replace('-', ' ')

    return {
        'title': title_rest.title()[:200],
        'location': location.title() + ', France'
    }

def scrape_wttj_jobs(
    search_term: str = "geomaticien",
    allowed_countries: List[str] = None,
    max_jobs: int = 50
) -> List[JobPosting]:
    """Scrape jobs from WTTJ using multiple category pages"""
    logger.info("Scraping WTTJ jobs")

    all_jobs = []
    seen_slugs = set()

    # Determine which pages to scrape based on search term
    pages_to_scrape = []
    if search_term.lower() in ['geomaticien', 'sig', 'gis']:
        pages_to_scrape = [CATEGORY_PAGES['developpeur'], CATEGORY_PAGES['informatique']]
    else:
        pages_to_scrape = list(CATEGORY_PAGES.values())[:3]

    for page_url in pages_to_scrape:
        if len(all_jobs) >= max_jobs:
            break

        try:
            logger.info(f"Fetching: {page_url}")
            response = requests.get(page_url, timeout=30)

            # Find all job URLs
            job_patterns = re.findall(r'/companies/([^/]+)/jobs/([^?"]+)', response.text)

            for company, job_slug in job_patterns:
                if job_slug in seen_slugs or len(all_jobs) >= max_jobs:
                    continue
                seen_slugs.add(job_slug)

                info = parse_wttj_job_slug(job_slug)

                job = JobPosting(
                    id=f"wttj-{job_slug[:30]}",
                    title=info['title'],
                    company=company.replace('-', ' ').title(),
                    location=info['location'],
                    description="WTTJ job",
                    url=f"https://www.welcometothejungle.com/companies/{company}/jobs/{job_slug}",
                    site="welcometothejungle"
                )

                if allowed_countries:
                    if is_allowed_country(job.location, allowed_countries):
                        all_jobs.append(job)
                else:
                    all_jobs.append(job)

        except Exception as e:
            logger.error(f"Error fetching {page_url}: {e}")

    logger.info(f"Created {len(all_jobs)} WTTJ job postings")
    return all_jobs
