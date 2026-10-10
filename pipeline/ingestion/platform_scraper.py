"""
Platform-specific scrapers for job sites
"""
import logging
import os
import time
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from .exceptions import ScraperError, TransientError
from .models import JobPosting

logger = logging.getLogger(__name__)

BLOCK_INDICATORS = {
    "captcha": ["captcha", "recaptcha", "hcaptcha", "i am not a robot"],
    "geo_block": ["access denied", "blocked", "not available in your region",
                  "geo-restricted", "not accessible from your location"],
    "cloudflare": ["cloudflare", "cf-browser-verification", "just a moment..."],
    "radware": ["radware", "security check", "bot protect"],
    "rate_limit": ["too many requests", "rate limit", "429 too many requests"],
}


def _detect_blocked(html: str) -> Optional[str]:
    """Check HTML for anti-bot / geo-blocking patterns. Returns block type or None."""
    html_lower = html.lower()
    for block_type, patterns in BLOCK_INDICATORS.items():
        for pattern in patterns:
            if pattern in html_lower:
                return block_type
    return None


def _retry_request(url: str, max_retries: int = 3, **kwargs) -> requests.Response:
    """GET with exponential backoff retry (1s, 2s, 4s). Raises TransientError if all retries fail."""
    timeout = kwargs.pop("timeout", 30)
    last_error: Optional[str] = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=timeout, **kwargs)
            if r.status_code < 500:
                return r
            logger.warning("HTTP %d on %s (attempt %d/%d)", r.status_code, url, attempt + 1, max_retries)
            last_error = f"HTTP {r.status_code}"
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.warning("Request failed: %s (attempt %d/%d)", e, attempt + 1, max_retries)
            last_error = str(e)
            if attempt == max_retries - 1:
                break
        time.sleep(1.0 * (2 ** attempt))
    raise TransientError(url, last_error or "max retries exceeded")


def _block_resources(page):
    """Block fonts, images, and CSS to speed up scraping."""
    page.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf,eot,css}",
               lambda route: route.abort())

def scrape_seek_au(max_jobs: int = 20) -> List[JobPosting]:
    """Scrape from seek.com.au (Australia)"""
    logger.info("Scraping seek.com.au...")

    all_jobs = []

    try:
        url = "https://www.seek.com.au/jobs"
        r = _retry_request(url)
        blocked = _detect_blocked(r.text)
        if blocked:
            logger.warning("seek.com.au: %s detected — returning 0 jobs", blocked)
            return []

        soup = BeautifulSoup(r.text, 'html.parser')

        articles = soup.find_all('article')

        for i, art in enumerate(articles[:max_jobs]):
            link = art.find('a', href=lambda x: x and '/job/' in x)
            if not link:
                continue

            href = link.get('href', '')
            url_job = f"https://www.seek.com.au{href}" if href.startswith('/') else href

            title = art.get('aria-label', '')
            if not title:
                heading = art.find(['h1', 'h2', 'h3'])
                title = heading.get_text(strip=True) if heading else ''

            if not title:
                continue

            job = JobPosting(
                id=f"seekau-{i}",
                title=title[:200],
                company="Unknown",
                location="Australia",
                description="Job from seek.com.au",
                url=url_job,
                site="seek_au"
            )
            all_jobs.append(job)

    except ScraperError as e:
        logger.warning("[%s] %s", e.code, e)
    except Exception as e:
        logger.error(f"seek.com.au error: {e}")

    logger.info(f"Created {len(all_jobs)} seek.au jobs")
    return all_jobs


def scrape_iamexpat_nl(max_jobs: int = 20) -> List[JobPosting]:
    """Scrape from iamexpat.nl (Netherlands)"""
    logger.info("Scraping iamexpat.nl...")

    all_jobs = []

    try:
        url = "https://www.iamexpat.nl"
        r = _retry_request(url, allow_redirects=True)
        soup = BeautifulSoup(r.text, 'html.parser')

        links = soup.find_all('a', href=lambda x: x and '/job' in x if x else False)

        for i, link in enumerate(links[:max_jobs]):
            title = link.get_text(strip=True)
            if not title or len(title) < 5:
                continue

            href = link.get('href', '')
            url_job = f"https://www.iamexpat.nl{href}" if href.startswith('/') else href

            job = JobPosting(
                id=f"iamexpat-{i}",
                title=title[:200],
                company="Unknown",
                location="Netherlands",
                description="Job from iamexpat.nl",
                url=url_job,
                site="iamexpat"
            )
            all_jobs.append(job)

    except ScraperError as e:
        logger.warning("[%s] %s", e.code, e)
    except Exception as e:
        logger.error(f"iamexpat.nl error: {e}")

    logger.info(f"Created {len(all_jobs)} iamexpat.nl jobs")
    return all_jobs


def scrape_jobs_lu(max_jobs: int = 20) -> List[JobPosting]:
    """Scrape from jobs.lu (Luxembourg)"""
    logger.info("Scraping jobs.lu...")

    all_jobs = []

    try:
        url = "https://en.jobs.lu"
        r = _retry_request(url)
        soup = BeautifulSoup(r.text, 'html.parser')

        links = soup.find_all('a', href=lambda x: x and '/job' in x if x else False)

        for i, link in enumerate(links[:max_jobs]):
            title = link.get_text(strip=True)
            if not title or len(title) < 5:
                continue

            href = link.get('href', '')
            url_job = f"https://en.jobs.lu{href}" if href.startswith('/') else href

            job = JobPosting(
                id=f"jobslu-{i}",
                title=title[:200],
                company="Unknown",
                location="Luxembourg",
                description="Job from jobs.lu",
                url=url_job,
                site="jobs_lu"
            )
            all_jobs.append(job)

    except ScraperError as e:
        logger.warning("[%s] %s", e.code, e)
    except Exception as e:
        logger.error(f"jobs.lu error: {e}")

    logger.info(f"Created {len(all_jobs)} jobs.lu jobs")
    return all_jobs


def _launch_scraper(url: str, job_selector: str, site: str, site_prefix: str,
                    location: str, max_jobs: int = 20) -> List[JobPosting]:
    """Reusable Playwright scraper: launches headless Chromium, blocks
    unnecessary resources, waits for job elements, extracts links."""
    from playwright.sync_api import sync_playwright

    headless = os.environ.get("PW_HEADLESS", "true").lower() == "true"
    all_jobs = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()

            _block_resources(page)

            page.goto(url, timeout=30000)
            page.wait_for_load_state("networkidle")

            try:
                page.wait_for_selector(job_selector, timeout=15000)
            except Exception as e:
                logger.warning("%s: job selector '%s' not found: %s", site, job_selector, e)

            jobs_data = page.evaluate(
                """({selector}) => Array.from(document.querySelectorAll(selector)).map(el => ({
                    href: el.href || el.getAttribute('href') || '',
                    title: (el.innerText || '').trim(),
                }))""",
                {"selector": job_selector},
            )

            seen = set()
            count = 0

            for item in jobs_data:
                title = item["title"]
                href = item["href"]
                if title and len(title) > 5 and href and title not in seen:
                    seen.add(title)
                    job_url = href if href.startswith("http") else f"https://{href}" if "://" not in href else href

                    job = JobPosting(
                        id=f"{site_prefix}-{count}",
                        title=title[:200],
                        company="Unknown",
                        location=location,
                        description=f"Job from {site}",
                        url=job_url,
                        site=site,
                    )
                    all_jobs.append(job)
                    count += 1

                    if count >= max_jobs:
                        break

            browser.close()
    except ScraperError as e:
        logger.warning("[%s] %s", e.code, e)
    except Exception as e:
        logger.error("%s error: %s", site, e)

    logger.info("Created %d %s jobs", len(all_jobs), site)
    return all_jobs


def scrape_jobat_be(max_jobs: int = 20) -> List[JobPosting]:
    """Scrape from jobat.be (Belgium) - uses JavaScript rendering"""
    return _launch_scraper(
        url="https://www.jobat.be/nl/jobs/data",
        job_selector="a[href*='/job/']",
        site="jobat_be",
        site_prefix="jobat",
        location="Belgium",
        max_jobs=max_jobs,
    )


def scrape_oikotie_fi(max_jobs: int = 20) -> List[JobPosting]:
    """Scrape from oikotie.fi (Finland) - uses JavaScript rendering"""
    return _launch_scraper(
        url="https://www.oikotie.fi/tyopaikat?hae=data",
        job_selector="a[href*='/tyopaik']",
        site="oikotie_fi",
        site_prefix="oikotie",
        location="Finland",
        max_jobs=max_jobs,
    )
