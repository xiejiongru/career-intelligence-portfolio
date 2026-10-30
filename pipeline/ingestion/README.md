# Ingestion

Generic ingestion adapters included in the public snapshot.

| File | Target type | Technique |
|---|---|---|
| `jobspy_scraper.py` | Aggregators (LinkedIn, Indeed) | JobSpy library |
| `ats_scraper.py` | ATS APIs (Greenhouse, Lever, SmartRecruiters) | Public APIs |
| `platform_scraper.py` | Platform job boards (Seek, Jobat, Oikotie, IamExpat, Jobs.lu) | requests + Playwright |
| `custom_scraper.py` | Generic custom URLs and GeoRezo | Crawl4AI + LLM extraction |
| `exceptions.py` | Structured scraper errors | `code` + `retryable` |

> Employer-specific career-site adapters are maintained in the private pipeline and are not published in this snapshot. The public adapters demonstrate the ingestion patterns without naming target employers.

## Structured errors (`exceptions.py`)

| Exception | code | retryable | Use |
|---|---|---|---|
| `BlockedError` | `BLOCKED_*` | false | Active blocking (geo-block / captcha / Radware) |
| `TransientError` | `TRANSIENT` | true | Temporary failure (timeout / connection reset / 5xx) |
| `ParseError` | `PARSE_FAILED` | false | Unexpected page structure (selector missing / format mismatch) |

Adapters catch `ScraperError` first for structured logging, then fall back to `Exception`.

## Platform scraper helpers (`platform_scraper.py`)

| Helper | Purpose |
|---|---|
| `_detect_blocked(html)` | Detect anti-bot signatures: captcha / geo_block / cloudflare / radware / rate_limit |
| `_retry_request(url, max_retries=3)` | GET with exponential backoff (1s → 2s → 4s); raises `TransientError` after exhaustion |
| `_block_resources(page)` | Block fonts, images and CSS in Playwright to speed up page loads |
| `_launch_scraper(url, selector, site, ...)` | Shared Playwright entry point: launch → block resources → `page.evaluate()` extraction |

`page.evaluate()` extracts all fields in one browser call instead of N+1 Python-to-browser round trips.

## Custom URL adapter (`custom_scraper.py`)

- Crawls configured URLs with Crawl4AI, then extracts structured postings with an LLM.
- Falls back to a plain HTTP request when the browser crawl fails.
- Keeps a 24-hour artifact cache to avoid re-crawling the same site.
- Handles GeoRezo forum posts with a regex extractor plus detail-page enrichment.

## Reference

- [Keep a Changelog](https://keepachangelog.com/) — changelog format
- [actionbook](https://actionbook.dev) — source of the structured error-code pattern
