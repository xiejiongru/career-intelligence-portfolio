"""EDF Job Scraper - Uses requests + regex like GeoRezo scraper."""

import json
import logging
import re
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from .models import JobPosting

logger = logging.getLogger(__name__)

EDF_BASE_URL = "https://www.edf.fr"
EDF_LISTINGS_URL = f"{EDF_BASE_URL}/edf-recrute/rejoignez-nous/voir-les-offres/nos-offres"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
}


def extract_job_id_from_url(url: str) -> Optional[str]:
    """Extract job ID from EDF job detail URL."""
    match = re.search(r'/detail/(\d+-\d+)', url)
    return match.group(1) if match else None


def parse_job_detail_page(html: str, job_url: str) -> Optional[JobPosting]:
    """Parse a single EDF job detail page and extract structured data."""
    try:
        soup = BeautifulSoup(html, 'html.parser')

        # Extract title from h1 or meta tag
        title_tag = soup.find('h1')
        if not title_tag:
            return None

        full_title = title_tag.get_text(strip=True)
        # Remove date prefix if present (e.g., "30 Avril 2026Chargé...")
        title_clean = re.sub(r'^\d+\s+\w+\s+\d{4}', '', full_title).strip()

        # Extract job ID
        job_id = extract_job_id_from_url(job_url)
        if not job_id:
            return None

        # Extract metadata from the page
        text_content = soup.get_text(separator='\n', strip=True)

        # Contract type (CDI, CDD, Stage, etc.)
        contract_match = re.search(r'Type de contrat\s*:\s*(CDI|CDD|Stage|Alternance|Apprentissage)', text_content, re.IGNORECASE)
        job_type = contract_match.group(1).upper() if contract_match else None

        # Location
        location_parts = []
        region_match = re.search(r'Pays / R[eé]gion\s*:\s*([^\n]+)', text_content)
        if region_match:
            location_parts.append(region_match.group(1).strip())

        ville_match = re.search(r'Ville\s*:\s*([^\n]+)', text_content)
        if ville_match:
            location_parts.append(ville_match.group(1).strip())

        location = ' / '.join(location_parts) if location_parts else 'France'

        # Education level
        edu_match = re.search(r'Niveau de formation\s*:\s*([^\n]+)', text_content)
        education = edu_match.group(1).strip() if edu_match else None

        # Experience
        exp_match = re.search(r'Exp[eé]rience\s*:\s*([^\n]+)', text_content)
        experience = exp_match.group(1).strip() if exp_match else None

        # Speciality
        spec_match = re.search(r'Sp[eé]cialit[eé]\(s\)\s*:\s*([^\n]+(?:\n[^\n]*)?)', text_content)
        spec_match.group(1).strip() if spec_match else None

        # Description - find the section after "Description de l'offre"
        desc_match = re.search(r'Description de l\'offre\s*\n(.*?)(?:Je postule|Postuler|$)', text_content, re.DOTALL)
        description = desc_match.group(1).strip() if desc_match else ''

        # Posted date
        date_match = re.search(r'Mise en ligne le\s*(\d{2}/\d{2}/\d{4})', text_content)
        date_posted = date_match.group(1) if date_match else None

        job = JobPosting(
            id=f"edf-{job_id}",
            title=title_clean,
            company='EDF',
            location=location,
            description=description[:2000],  # Limit description length
            url=job_url,
            site='edf',
            job_type=job_type,
            education=education,
            experience=experience,
            date_posted=date_posted,
        )

        return job

    except Exception as e:
        logger.error(f"Error parsing job detail page {job_url}: {e}")
        return None


def scrape_edf_jobs(max_jobs: int = 20) -> List[JobPosting]:
    """
    Scrape EDF job postings using requests (similar to GeoRezo approach).

    Args:
        max_jobs: Maximum number of jobs to scrape (default: 20)

    Returns:
        List of JobPosting objects
    """
    logger.info(f"Starting EDF job scraping (max {max_jobs} jobs)...")

    all_jobs = []
    page = 0
    max_pages = 10  # Safety limit

    while page < max_pages and len(all_jobs) < max_jobs:
        # Build URL with pagination
        if page == 0:
            url = EDF_LISTINGS_URL
        else:
            url = f"{EDF_LISTINGS_URL}?page={page}"

        logger.info(f"Fetching listings page {page + 1}: {url}")

        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to fetch {url}: {e}")
            break

        soup = BeautifulSoup(response.text, 'html.parser')

        # Find job detail links with pattern: /edf-recrute/offre/detail/YYYY-NNNNNN
        job_links = soup.find_all('a', href=re.compile(r'/edf-recrute/offre/detail/\d+-\d+'))

        if not job_links:
            logger.info(f"No more jobs found on page {page + 1}")
            break

        logger.info(f"Found {len(job_links)} job links on page {page + 1}")

        for link in job_links:
            if len(all_jobs) >= max_jobs:
                break

            job_url = link.get('href', '')
            if not job_url.startswith('http'):
                job_url = EDF_BASE_URL + job_url

            # Avoid duplicates
            if any(j.url == job_url for j in all_jobs):
                continue

            logger.info(f"  Fetching detail: {job_url}")

            try:
                detail_response = requests.get(job_url, headers=HEADERS, timeout=30)
                detail_response.raise_for_status()

                job_data = parse_job_detail_page(detail_response.text, job_url)
                if job_data:
                    all_jobs.append(job_data)
                    logger.info(f"    ✓ Parsed: {job_data.title[:60]} | {job_data.location}")
                else:
                    logger.warning(f"    ✗ Failed to parse: {job_url}")

            except Exception as e:
                logger.error(f"    ✗ Error fetching detail: {e}")

        # Check for next page
        next_link = soup.find('a', class_=re.compile(r'next|suivant|pagination.*next', re.I))
        if not next_link:
            # Try alternative pagination detection
            pagination_nav = soup.find('nav', class_=re.compile(r'pagination'))
            if pagination_nav:
                current_page_elem = pagination_nav.find('span', class_='active') or pagination_nav.find('li', class_='active')
                if current_page_elem:
                    pass  # Continue to check for next page link
                else:
                    break
            else:
                break

        page += 1

    logger.info(f"Successfully scraped {len(all_jobs)} jobs from EDF")
    return all_jobs


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    max_jobs = int(sys.argv[1]) if len(sys.argv) > 1 else 10

    jobs = scrape_edf_jobs(max_jobs=max_jobs)

    print(f"\n\nTotal jobs scraped: {len(jobs)}")
    print("\nSample jobs:")
    for job in jobs[:3]:
        print(json.dumps(job, indent=2, ensure_ascii=False))

    # Save to JSON
    output_file = 'edf_jobs_scraped.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {output_file}")
