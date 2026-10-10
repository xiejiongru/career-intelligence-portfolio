"""
Magellium scraper
"""
import logging
from typing import List

import requests
from bs4 import BeautifulSoup

from .models import JobPosting

logger = logging.getLogger(__name__)

def scrape(max_jobs: int = 30) -> List[JobPosting]:
    """Scrape Magellium careers page"""
    logger.info("Scraping Magellium...")

    all_jobs = []

    try:
        r = requests.get("https://www.magellium.com/carriere", timeout=30,
                         headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(r.text, 'html.parser')

        links = soup.find_all('a', href=lambda x: x and '/offre_emploi/' in x if x else False)

        seen_urls = set()
        count = 0

        for link in links:
            if count >= max_jobs:
                break

            href = link.get('href', '').strip()
            title = link.get_text(strip=True)

            if not title or not href:
                continue
            if 'Voir' in title and len(title) < 10:
                continue
            if href in seen_urls:
                continue

            seen_urls.add(href)

            if not href.startswith('http'):
                href = f"https://www.magellium.com{href}"

            job = JobPosting(
                id=f"magellium-{count}",
                title=title[:200],
                company="Magellium",
                location="France",
                description="Job from Magellium",
                url=href,
                site="magellium"
            )
            all_jobs.append(job)
            count += 1

    except Exception as e:
        logger.error(f"Magellium error: {e}")

    logger.info(f"Created {len(all_jobs)} Magellium jobs")
    return all_jobs
