"""
AAE-ENSG job board scraper (French geomatics school alumni).
Salary >= 3200 €/mois -> "3200 以上"
"""
import logging
import re
from typing import List

import requests
from bs4 import BeautifulSoup

from .models import JobPosting

logger = logging.getLogger(__name__)

SALARY_THRESHOLD = 3200

BASE_URL = "https://www.aae-ensg.eu/blog/category/offres-emploi/"
SITE = "aae_ensg"
SITE_PREFIX = "aae"


def _parse_salary(text: str) -> str:
    """Extract salary from French job text. Returns '3200 以上' if >= threshold."""
    if not text:
        return ""

    patterns = [
        (r'(\d[\d\s]*)\s*€\s*brut\s*/?\s*mois', False),
        (r'(\d[\d\s]*)\s*€\s*/?\s*mois', False),
        (r'(\d[\d\s]*)\s*€\s*brut\s*an', True),
        (r'(\d[\d\s]*)\s*€\s*/?\s*an', True),
        (r'(\d+)\s*k\s*€?', True),
        (r'(\d+)\s*k€', True),
    ]

    for pat, is_annual in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            amount_str = m.group(1).replace(' ', '')
            try:
                amount = float(amount_str)
            except ValueError:
                continue

            if is_annual:
                amount_monthly = amount * 1000 / 12 if 'k' in pat else amount / 12
            else:
                amount_monthly = amount

            if amount_monthly >= SALARY_THRESHOLD:
                return "3200 以上"

    return ""


def _extract_location(text: str) -> str:
    m = re.search(r'Lieu\s*:\s*(.+?)(?:[•\n]|$)', text)
    if m:
        return m.group(1).strip()
    m = re.search(r'à\s+([A-Z][a-zéèêëàâîïôûùç\-]+(?:\s+\(?\d+\)?)?)', text)
    if m:
        return m.group(1).strip()
    return ""


def scrape(max_jobs: int = 20) -> List[JobPosting]:
    """Scrape from AAE-ENSG job board (French geomatics school alumni)"""
    logger.info("Scraping AAE-ENSG job board...")

    all_jobs = []

    try:
        r = requests.get(BASE_URL, timeout=30)
        soup = BeautifulSoup(r.text, 'html.parser')
        articles = soup.find_all('article')

        for i, art in enumerate(articles[:max_jobs]):
            try:
                title_el = art.find('h1') or art.find('h2')
                if not title_el:
                    continue
                link = title_el.find('a')
                if not link:
                    continue

                title = link.get_text(strip=True)
                job_url = link.get('href', '')
                if not title:
                    continue

                full_text = art.get_text(separator=' ', strip=True)
                salary = _parse_salary(full_text)
                location = _extract_location(full_text)

                desc_p = art.find('p')
                description = desc_p.get_text(strip=True) if desc_p else ""

                job = JobPosting(
                    id=f"{SITE_PREFIX}-{i}",
                    title=title[:200],
                    company="AAE-ENSG",
                    location=location or "France",
                    description=description[:500] if description else "Job from AAE-ENSG",
                    url=job_url,
                    site=SITE,
                    salary=salary,
                )
                all_jobs.append(job)

            except Exception:
                continue

    except Exception as e:
        logger.error("AAE-ENSG error: %s", e)

    logger.info("Created %d AAE-ENSG jobs", len(all_jobs))
    return all_jobs
