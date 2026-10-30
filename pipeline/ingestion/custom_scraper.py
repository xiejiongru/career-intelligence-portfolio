import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from typing import List, Optional

import httpx
import requests
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from openai import OpenAI

from ..matching.schemas import ExtractedJob, parse_json_list
from .models import JobPosting

logger = logging.getLogger(__name__)

# ── Page timeout (seconds) ────────────────────────────────────────────────────
PAGE_TIMEOUT_MS = 30_000          # 30 s per page
DETAIL_TIMEOUT_S = 40             # asyncio timeout wrapping detail-page crawl
MAX_CONCURRENT_CRAWLS = 3         # max parallel browser tabs

# ── Browser User-Agent for anti-bot detection ─────────────────────────────────
BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ── Domain → source label mapping ────────────────────────────────────────────
CORPORATE_SITE_MAP = {
    "georezo.net": "georezo",
}

# ── Site-specific crawl configuration ────────────────────────────────────────
SITE_CRAWL_CONFIGS = {
    "georezo": {
        "css_selector": ".postmsg",  # GeoRezo post body
    },
}

def _resolve_site(url: str) -> str:
    """Return a source label for the URL, or 'custom' if unmatched."""
    for domain, site in CORPORATE_SITE_MAP.items():
        if domain in url:
            return site
    return "custom"

def _get_crawl_config_for_site(site: str, base_config: CrawlerRunConfig) -> CrawlerRunConfig:
    """Return site-specific crawl config, falling back to the base config."""
    site_config = SITE_CRAWL_CONFIGS.get(site, {})

    if not site_config:
        return base_config

    # Build a new config that inherits the base and overrides specific fields
    kwargs = {
        "cache_mode": base_config.cache_mode,
        "page_timeout": site_config.get("page_timeout", base_config.page_timeout),
    }

    # Add css_selector only when explicitly configured
    if "css_selector" in site_config:
        kwargs["css_selector"] = site_config["css_selector"]

    # Add custom JS when configured
    if "js_code" in site_config:
        kwargs["js_code"] = site_config["js_code"]

    return CrawlerRunConfig(**kwargs)

def extract_jobs_georezo_regex(content: str, source_url: str) -> List[JobPosting]:
    extracted_jobs = []
    # pattern captures [TYPE] Title (with optional markdown link) par Author
    pattern = r'\[([A-Z/ ]+)\]\s*(.*?)\s*par\s*([^|\n\r]+)'

    matches = re.finditer(pattern, content)
    for match in matches:
        job_type = match.group(1).strip()
        remaining = match.group(2).strip()
        company = match.group(3).strip()

        detail_url = source_url
        # Try to extract URL from markdown link: [Title](URL)
        link_match = re.search(r'(.*)\]\((https?://georezo\.net/forum/viewtopic\.php\?id=\d+)\)', remaining)
        if link_match:
            title_part = link_match.group(1).strip()
            detail_url = link_match.group(2).strip()
        else:
            title_part = remaining

        # Try to separate title and location
        if " - " in title_part:
            parts = title_part.split(" - ", 1)
            title = parts[0].strip()
            location = parts[1].strip()
        else:
            title = title_part
            location = "Unknown"

        full_title = f"[{job_type}] {title}"

        # Unique ID
        job_id = f"georezo-{re.sub(r'[^a-zA-Z0-9]', '-', full_title.lower())}-{re.sub(r'[^a-zA-Z0-9]', '-', company.lower())}"

        job = JobPosting(
            id=job_id,
            title=full_title,
            company=company,
            location=location,
            description=f"Type: {job_type}. Extracted from GeoRezo forum.",
            url=detail_url,
            site="georezo"
        )
        extracted_jobs.append(job)

    logger.info(f"Regex extracted {len(extracted_jobs)} jobs from GeoRezo")
    return extracted_jobs

async def extract_jobs_from_content(content: str, source_url: str, client: OpenAI, model: str) -> List[JobPosting]:
    """
    Prefer regex extraction for GeoRezo posts; use a dedicated LLM prompt for
    company sites. Company-site extraction validates with the ExtractedJob
    Pydantic schema, eliminating malformed JSON from non-deterministic LLM
    output.
    """
    if "georezo.net" in source_url:
        logger.info(f"Bypassing LLM for {source_url}, using regex extraction.")
        return extract_jobs_georezo_regex(content, source_url)

    site = _resolve_site(source_url)
    logger.info(f"Using LLM to extract jobs for {source_url} (site={site})...")

    # Company-site prompt: focus on French roles and keep only Data/GIS/DevOps/SIG postings.
    # Require a plain JSON array (no markdown fences).
    prompt = f"""\
You are an expert job scraper working on behalf of a GIS/Data/DevOps engineer in France.
Extract ALL job postings from the markdown content below.

IMPORTANT RULES:
- Only include jobs located in France (or "France" / "Remote" with French context).
- Prioritise roles related to: GIS, SIG, Géomatique, Data Engineering, DevOps, Python, SQL, Spatial Data, Cloud, ETL.
- If the page contains no relevant jobs, return an empty JSON list: []

For each job return a JSON object with EXACTLY these fields:
  id          – unique slug (lowercase, hyphens)
  title       – full job title
  company     – hiring company name
  location    – city / region in France
  description – 2–4 sentence summary of key responsibilities and required skills
  url         – direct link to the job detail page (use "{source_url}" if not found)
  job_type    – one of: CDI, CDD, Internship, Apprentissage, Stage, or null
  salary      – salary info if visible, else null
  remote      – "Yes" / "Partial" / "No" / null
  experience  – required years/level if stated, else null
  education   – required degree if stated, else null

Return ONLY a raw JSON list. No markdown fences, no explanation.

Content (first 8000 chars):
{content[:8000]}
"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        raw_json = response.choices[0].message.content

        # Validate and clean with the Pydantic schema
        extracted: List[ExtractedJob] = parse_json_list(raw_json, ExtractedJob, max_retries=3)

        # Convert to JobPosting dataclass
        extracted_jobs: List[JobPosting] = []
        for j in extracted:
            extracted_jobs.append(JobPosting(
                id=j.id or f"custom-{hash(j.title)}",
                title=j.title,
                company=j.company,
                location=j.location,
                description=j.description,
                url=j.url or source_url,
                site=site,
                job_type=j.job_type,
                salary=j.salary,
                remote=j.remote,
                experience=j.experience,
                education=j.education
            ))
        logger.info(f"LLM extracted {len(extracted_jobs)} jobs from {source_url}")
        return extracted_jobs
    except Exception as e:
        logger.error(f"LLM extraction failed for {source_url}: {e}")
        return []

def _enrich_georezo_job(job: JobPosting, raw_markdown: str) -> None:
    """In-place enrichment of a GeoRezo job from its detail page markdown."""
    # 1. Strip and basic cleanup
    clean_desc = raw_markdown.strip()
    # 2. Remove lines that are just repeated characters or symbols
    clean_desc = re.sub(r'^[=\-_*#\s]{3,}$', '', clean_desc, flags=re.MULTILINE)
    # 3. Handle multiple newlines
    clean_desc = re.sub(r'\n{3,}', '\n\n', clean_desc)
    # 4. Remove forum-specific noise
    clean_desc = re.sub(r'_Dernière modification par.*_', '', clean_desc)
    clean_desc = re.sub(r'\[!\[banniere\].*?\]\(.*?\)', '', clean_desc)
    # 5. Final trim
    job.description = clean_desc.strip()

    # Job Type (CDI, CDD, etc.)
    type_match = re.search(r'\b(CDI|CDD|Alternance|Apprentissage|Stage|FPT)\b', job.title + " " + job.description, re.IGNORECASE)
    if type_match:
        job.job_type = type_match.group(1).upper()

    # Salary
    salary_match = re.search(r'(\d+[\s\d]*[€]|(\d+[\s\d]*)\s*(euros|bruts?|mensuels?|annuels?))', job.description, re.IGNORECASE)
    if salary_match:
        job.salary = salary_match.group(0).strip()

    # Education
    edu_match = re.search(r'(Bac\s*\+\s*\d|Master|Licence|Ingénieur)', job.description, re.IGNORECASE)
    if edu_match:
        job.education = edu_match.group(1).strip()

    # Experience
    exp_match = re.search(r'(\d+)\s*(ans?|années?)\s*d[\'\ ]expérience', job.description, re.IGNORECASE)
    if exp_match:
        job.experience = exp_match.group(0).strip()

    # Remote
    remote_match = re.search(r'(Télétravail|Remote|Travail à distance)', job.description, re.IGNORECASE)
    if remote_match:
        job.remote = remote_match.group(1).strip()

    # Date Posted
    date_match = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', job.description)
    if date_match:
        job.date_posted = date_match.group(1)
    else:
        date_match = re.search(r'(?:Posté le|Le)\s*(\d{1,2}\s+\w+\s+\d{4})', job.description, re.IGNORECASE)
        if date_match:
            job.date_posted = date_match.group(1)


def _fetch_with_requests(url: str, timeout: int = 30) -> Optional[str]:
    """Fallback: fetch page content using requests library.

    Returns HTML content or None if failed.
    """
    try:
        headers = {
            'User-Agent': BROWSER_USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        }
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        logger.info(f"[HTTP Fallback] Successfully fetched {len(response.text)} chars from {url}")
        return response.text
    except Exception as e:
        logger.error(f"[HTTP Fallback] Failed to fetch {url}: {e}")
        return None


async def _crawl_url(crawler: "AsyncWebCrawler", url: str, run_config: "CrawlerRunConfig",
                     semaphore: asyncio.Semaphore, cookies: list = None) -> tuple[str, object]:
    """Acquire semaphore, crawl a single URL, and return (url, result).

    Args:
        crawler: AsyncWebCrawler instance
        url: URL to crawl
        run_config: CrawlerRunConfig with page settings
        semaphore: Asyncio semaphore for concurrency control
        cookies: Optional list of cookie dicts [{'name': '...', 'value': '...', 'domain': '...'}, ...]
    """
    async with semaphore:
        try:
            # Add cookies if provided
            if cookies:
                logger.debug(f"Setting {len(cookies)} cookies for {url}")
                await crawler.set_cookies(cookies)

            result = await asyncio.wait_for(
                crawler.arun(url=url, config=run_config),
                timeout=PAGE_TIMEOUT_MS / 1000 + 5  # give a bit more than the browser timeout
            )
            return url, result
        except asyncio.TimeoutError:
            logger.error(f"Timeout crawling {url} after {PAGE_TIMEOUT_MS/1000:.0f}s")
            return url, None
        except Exception as e:
            logger.error(f"Exception crawling {url}: {e}")
            return url, None


def _parse_cookie_string(cookie_str: str, domain: str) -> list:
    """Parse a cookie string into a list of cookie dicts for Crawl4AI.

    Args:
        cookie_str: Cookie string like "name1=value1; name2=value2;"
        domain: Domain for the cookies (e.g., 'careers.se.com')

    Returns:
        List of cookie dicts
    """
    cookies = []
    for item in cookie_str.split(';'):
        item = item.strip()
        if '=' in item:
            name, value = item.split('=', 1)
            cookies.append({
                'name': name.strip(),
                'value': value.strip(),
                'domain': domain,
                'path': '/'
            })
    return cookies


async def scrape_custom_urls(search_config: dict, llm_config: dict) -> List[JobPosting]:
    if "search" in search_config and "custom_urls" not in search_config:
        llm_config = search_config.get("llm", llm_config)
        search_config = search_config.get("search", {})

    custom_urls = search_config.get("custom_urls", [])
    if not custom_urls:
        return []

    # Load cookies from config (if any)
    cookies_config = search_config.get("cookies") or {}

    # Load allowed countries list from config (for scrapers that support filtering)
    allowed_countries = search_config.get("allowed_countries", [])
    if allowed_countries:
        logger.info(f"Using allowed countries filter: {len(allowed_countries)} countries configured")

    # Load country name mapping from config (for non-English country names)
    country_name_mapping = search_config.get("country_name_mapping", {})
    if country_name_mapping:
        logger.info(f"Using country name mapping: {len(country_name_mapping)} mappings configured")

    all_jobs: List[JobPosting] = []

    # ATS jobs - run these always as they're API-based
    if not custom_urls:
        logger.info("Running ATS scrapers")
    else:
        logger.info(f"Running ATS scrapers alongside {len(custom_urls)} custom URLs")

    try:
        from .ats_scraper import scrape_ats_jobs
        ats_cfg = search_config.get('ats_companies', {})
        gh = ats_cfg.get('greenhouse', [])
        lv = ats_cfg.get('lever', [])
        sr = ats_cfg.get('smartrecruiters', [])

        if gh:
            all_jobs.extend(scrape_ats_jobs(ats_type="greenhouse", companies=gh, allowed_countries=allowed_countries, max_jobs=30))
        if lv:
            all_jobs.extend(scrape_ats_jobs(ats_type="lever", companies=lv, allowed_countries=allowed_countries, max_jobs=20))
        if sr:
            all_jobs.extend(scrape_ats_jobs(ats_type="smartrecruiters", companies=sr, allowed_countries=allowed_countries, max_jobs=20))
    except Exception as e:
        logger.error(f"ATS scraper error: {e}")

    # Platform-specific scrapers (always run)
    logger.info("Running platform scrapers...")
    try:
        from .platform_scraper import (
            scrape_iamexpat_nl,
            scrape_jobat_be,
            scrape_jobs_lu,
            scrape_oikotie_fi,
            scrape_seek_au,
        )

        all_jobs.extend(scrape_seek_au(max_jobs=15))
        all_jobs.extend(scrape_jobat_be(max_jobs=15))
        all_jobs.extend(scrape_oikotie_fi(max_jobs=10))
        all_jobs.extend(scrape_iamexpat_nl(max_jobs=15))
        all_jobs.extend(scrape_jobs_lu(max_jobs=15))

    except Exception as e:
        logger.error(f"Platform scraper error: {e}")

    # Return early if only using ATS (no custom URLs needed)
    if not custom_urls:
        logger.info(f"Returning {len(all_jobs)} jobs from ATS scrapers")
        return all_jobs

    # Initialize OpenAI client for extraction
    api_key = "ollama"
    base_url = llm_config.get("base_url", "http://localhost:11434/v1")

    # Check whether a cloud API is configured (reserved path)
    cloud_config = llm_config.get("cloud", {})
    if cloud_config.get("enabled", False):
        logger.info("Cloud Ollama API is enabled, but we are currently prioritizing local regex for GeoRezo.")

    http_client = httpx.Client(trust_env=False)
    client = OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)
    model = llm_config.get("model", "qwen2.5:7b-instruct")

    # ── Check artifacts directory for recently scraped URLs (within 24h) ──────
    now = datetime.now()
    cutoff_time = now - timedelta(hours=24)

    # Build a mapping: custom_url -> site_name based on CORPORATE_SITE_MAP
    url_to_site = {}
    for url in custom_urls:
        url_to_site[url] = _resolve_site(url)

    # Scan artifacts to find which sites were scraped within 24h
    recently_scraped_sites = set()
    artifacts_dir = "artifacts"
    if os.path.exists(artifacts_dir):
        # Scan all date directories
        for date_dir in os.listdir(artifacts_dir):
            date_path = os.path.join(artifacts_dir, date_dir)
            if not os.path.isdir(date_path):
                continue

            # Check if this directory is within 24 hours by comparing dates
            try:
                dir_date = datetime.strptime(date_dir, "%Y-%m-%d")
                if dir_date < cutoff_time.replace(hour=0, minute=0, second=0, microsecond=0):
                    continue  # Skip old directories
            except ValueError:
                continue

            # Get directory modification time as additional check
            dir_mtime = datetime.fromtimestamp(os.path.getmtime(date_path))
            if dir_mtime < cutoff_time:
                continue

            # Scan batch directories
            for batch_dir in os.listdir(date_path):
                batch_path = os.path.join(date_path, batch_dir)
                if not os.path.isdir(batch_path):
                    continue

                # Check batch directory modification time
                batch_mtime = datetime.fromtimestamp(os.path.getmtime(batch_path))
                if batch_mtime < cutoff_time:
                    continue

                # Look for output.json files in site subdirectories
                for site_dir in os.listdir(batch_path):
                    site_output = os.path.join(batch_path, site_dir, "output.json")
                    if os.path.exists(site_output):
                        # Check if this file was modified within 24h
                        file_mtime = datetime.fromtimestamp(os.path.getmtime(site_output))
                        if file_mtime >= cutoff_time:
                            recently_scraped_sites.add(site_dir)

    logger.info(f"Found {len(recently_scraped_sites)} recently scraped sites in artifacts (within 24h): {recently_scraped_sites}")

    # Determine which URLs are due for crawling
    urls_to_crawl = []
    for url in custom_urls:
        site_name = url_to_site[url]
        if site_name in recently_scraped_sites:
            logger.info(f"Skipping {url} (site={site_name}), already scraped within last 24h (found in artifacts)")
            continue
        urls_to_crawl.append(url)

    if not urls_to_crawl:
        logger.info("All custom URLs are up-to-date. Nothing to crawl.")
        return all_jobs  # Return any jobs collected so far (e.g., from ATS/platform scrapers)

    # ── Configure Crawl4AI ────────────────────────────────────────────────────
    browser_config = BrowserConfig(
        headless=True,
        verbose=False,
        user_agent=BROWSER_USER_AGENT,  # Set realistic User-Agent
        use_persistent_context=False,   # Use fresh browser context each time
        # Additional anti-detection settings
        extra_args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-extensions",
        ],
    )
    base_run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=PAGE_TIMEOUT_MS,
        simulate_user=True,  # Simulate human-like behavior
        override_navigator=True,  # Override navigator properties to avoid detection
        wait_for="body",  # Wait for body to load
        delay_before_return_html=2.0,  # Wait 2 seconds before capturing HTML
    )
    detail_run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        css_selector=".postmsg",   # GeoRezo post body only
        page_timeout=PAGE_TIMEOUT_MS,
        simulate_user=True,
        override_navigator=True,
        delay_before_return_html=1.0,
    )

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CRAWLS)

    async with AsyncWebCrawler(config=browser_config) as crawler:

        # ── Step 1: Crawl all top-level URLs in parallel with site-specific configs ──
        logger.info(f"Crawling {len(urls_to_crawl)} URL(s) in parallel (max {MAX_CONCURRENT_CRAWLS} concurrent)...")

        # Create site-specific configs for each URL
        crawl_tasks = []
        for url in urls_to_crawl:
            site_name = url_to_site[url]
            site_config = _get_crawl_config_for_site(site_name, base_run_config)

            # Extract domain from URL for cookie matching
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc

            # Get cookies for this domain (if configured)
            domain_cookies = None
            if domain in cookies_config:
                cookie_str = cookies_config[domain]
                domain_cookies = _parse_cookie_string(cookie_str, domain)
                logger.info(f"  - {url} (site={site_name}, timeout={site_config.page_timeout}ms, cookies={len(domain_cookies)})")
            else:
                logger.info(f"  - {url} (site={site_name}, timeout={site_config.page_timeout}ms)")

            crawl_tasks.append(_crawl_url(crawler, url, site_config, semaphore, domain_cookies))

        crawl_results = await asyncio.gather(*crawl_tasks)

        # ── Step 2: Extract jobs from each crawled page ───────────────────────
        for url, result in crawl_results:
            # If Crawl4AI failed, try simple HTTP request as fallback
            if result is None or not result.success:
                err = result.error_message if result else "timeout"
                logger.warning(f"Crawl4AI failed for {url}: {err}")
                logger.info(f"Trying HTTP fallback for {url}...")

                html_content = _fetch_with_requests(url)
                if html_content:
                    # Convert HTML to a simple format for LLM extraction
                    # Remove scripts and styles to reduce noise
                    clean_html = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
                    clean_html = re.sub(r'<style[^>]*>.*?</style>', '', clean_html, flags=re.DOTALL | re.IGNORECASE)

                    logger.info(f"HTTP fallback successful, processing {len(clean_html)} chars")
                    jobs = await extract_jobs_from_content(clean_html, url, client, model)
                    all_jobs.extend(jobs)
                    continue
                else:
                    logger.error(f"Both Crawl4AI and HTTP fallback failed for {url}")
                    continue

            markdown_content = result.markdown
            logger.info(f"Crawled {len(markdown_content)} chars from {url}, processing extraction")

            jobs = await extract_jobs_from_content(markdown_content, url, client, model)

            # ── Step 3: Enrich GeoRezo job detail pages (sequential, rate-friendly) ──
            if "georezo.net" in url:
                logger.info(f"Enriching descriptions for {len(jobs)} GeoRezo jobs...")
                for i, job in enumerate(jobs):
                    if job.url == url:
                        continue  # no detail page available
                    try:
                        logger.info(f"  [{i+1}/{len(jobs)}] Scraping {job.url}")
                        detail_url_result, detail_result = await _crawl_url(
                            crawler, job.url, detail_run_config, semaphore
                        )
                        if detail_result and detail_result.success:
                            _enrich_georezo_job(job, detail_result.markdown)
                            logger.info(f"  ✓ Enriched: {job.title[:60]}")
                        else:
                            err = detail_result.error_message if detail_result else "timeout"
                            logger.warning(f"  ✗ Failed to enrich {job.url}: {err}")
                    except Exception as e:
                        logger.error(f"  Error enriching {job.url}: {e}")

            all_jobs.extend(jobs)

    return all_jobs
