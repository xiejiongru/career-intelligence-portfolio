"""
TotalEnergies Careers Scraper
Scrapes job listings from TotalEnergies Taleo-based careers portal
"""
import logging
from typing import List

from playwright.sync_api import sync_playwright

from .models import JobPosting

logger = logging.getLogger(__name__)

def scrape_totalenergies_jobs(max_jobs: int = 50) -> List[JobPosting]:
    """
    Scrape jobs from TotalEnergies careers portal.

    Args:
        max_jobs: Maximum number of jobs to scrape

    Returns:
        List of JobPosting objects
    """
    logger.info(f"Scraping TotalEnergies jobs (max {max_jobs})...")

    all_jobs = []

    try:
        p = sync_playwright().start()
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()

        # Navigate to careers page
        url = "https://jobs.totalenergies.com/fr_FR/careers/SearchJobs"
        logger.info(f"Navigating to {url}")
        page.goto(url, wait_until="load", timeout=30000)
        page.wait_for_timeout(5000)  # Wait for JavaScript to load

        # Find all job detail links
        all_links = page.query_selector_all("a[href]")
        logger.info(f"Found {len(all_links)} total links")

        job_count = 0
        for link in all_links:
            if job_count >= max_jobs:
                break

            href = link.get_attribute("href")
            if "/JobDetail/" not in href:
                continue

            title = link.text_content().strip()
            if len(title) < 5 or "charte" in title.lower() or "privacy" in title.lower():
                continue

            # Extract location from URL or title (simplified)
            location = "France"  # Default, could be extracted from detail page

            job = JobPosting(
                id=f"totalenergies-{job_count}",
                title=title,
                company="TotalEnergies",
                location=location,
                description="",  # Would need to visit detail page
                url=href,
                site="totalenergies",
            )
            all_jobs.append(job)
            job_count += 1

        browser.close()
        p.stop()

        logger.info(f"Successfully scraped {len(all_jobs)} jobs from TotalEnergies")
        return all_jobs

    except Exception as e:
        logger.error(f"Failed to scrape TotalEnergies: {e}")
        return []


if __name__ == "__main__":
    jobs = scrape_totalenergies_jobs()
    print(f"Total jobs: {len(jobs)}")
    for job in jobs[:5]:
        print(f"  - {job.title} ({job.location})")
