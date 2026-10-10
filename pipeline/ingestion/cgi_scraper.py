"""
CGI scraper - blocked by Radware bot protection
"""
import logging
from typing import List

from .models import JobPosting

logger = logging.getLogger(__name__)

def scrape(max_jobs: int = 20) -> List[JobPosting]:
    """Scrape CGI jobs - currently blocked by Radware bot protection"""
    logger.warning("CGI careers blocked by Radware bot protection - cannot scrape")

    # Try with requests first
    try:
        import requests
        r = requests.get(
            "https://cgi.njoyn.com/corp/xweb/xweb.asp?NTKN=c&clid=21001&Page=joblisting",
            timeout=30,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            }
        )
        if 'captcha' in r.text.lower():
            logger.warning("CGI: Radware captcha detected")
    except Exception as e:
        logger.error(f"CGI error: {e}")

    logger.info("CGI scraper returned 0 jobs (blocked by Radware)")
    return []
