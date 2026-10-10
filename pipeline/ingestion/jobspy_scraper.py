import logging
from typing import List

from jobspy import scrape_jobs

from .models import JobPosting

logger = logging.getLogger(__name__)

def scrape(config: dict) -> List[JobPosting]:
    """JobSpy scraper - supports keyword and company search"""
    logger.info(f"Starting JobSpy for sites: {config['sites']}")

    weeks_back = config.get('weeks_back', 2)
    days_back = weeks_back * 7

    all_jobs = []

    # Keyword search
    for keyword in config.get("keywords", []):
        logger.info(f"Scraping for keyword: {keyword}")
        try:
            jobs_df = scrape_jobs(
                site_name=config["sites"],
                search_term=keyword,
                location=config["location"],
                results_wanted=config["results_per_site"],
                is_remote=config.get("remote_only", False),
                days_since_posted=days_back,
            )

            if jobs_df is None or jobs_df.empty:
                logger.warning(f"No results for keyword '{keyword}'")
                continue

            logger.info(f"Found {len(jobs_df)} jobs for '{keyword}'")

            for _, row in jobs_df.iterrows():
                desc = str(row.get("description", "") or "")
                if not desc:
                    desc = "Description not available from JobSpy."

                job = JobPosting(
                    id=str(row.get("id", "") or row.get("job_url", "")),
                    title=str(row.get("title", "")),
                    company=str(row.get("company", "")),
                    location=str(row.get("location", "")),
                    description=desc,
                    url=str(row.get("job_url", "")),
                    site=str(row.get("site", ""))
                )
                all_jobs.append(job)
        except Exception as e:
            logger.error(f"Error scraping '{keyword}': {e}")

    # Company search
    for company in config.get("company_search", []):
        logger.info(f"Scraping company: {company}")
        try:
            jobs_df = scrape_jobs(
                site_name=config["sites"],
                company_name=company,
                search_term="",
                location=config["location"],
                results_wanted=config["results_per_site"],
                is_remote=config.get("remote_only", False),
                days_since_posted=days_back,
            )

            if jobs_df is None or jobs_df.empty:
                logger.warning(f"No results for company '{company}'")
                continue

            logger.info(f"Found {len(jobs_df)} jobs from '{company}'")

            for _, row in jobs_df.iterrows():
                desc = str(row.get("description", "") or "")
                if not desc:
                    desc = "Description not available from JobSpy."

                job = JobPosting(
                    id=str(row.get("id", "") or row.get("job_url", "")),
                    title=str(row.get("title", "")),
                    company=str(row.get("company", "")),
                    location=str(row.get("location", "")),
                    description=desc,
                    url=str(row.get("job_url", "")),
                    site=str(row.get("site", ""))
                )
                all_jobs.append(job)
        except Exception as e:
            logger.error(f"Error scraping company '{company}': {e}")

    # Deduplicate
    unique_jobs = {job.id: job for job in all_jobs}.values()

    logger.info(f"Total unique jobs: {len(unique_jobs)}")

    return list(unique_jobs)
