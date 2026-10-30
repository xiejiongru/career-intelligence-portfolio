"""
Structured error recovery for scrapers
"""
import logging
from typing import Callable, Optional, TypeVar

T = TypeVar('T')
logger = logging.getLogger(__name__)


def safe_scrape(name: str, func: Callable[[], T], fallback: Optional[T] = None) -> T:
    """Execute a scraper with safe fallback"""
    try:
        result = func()
        if result is None:
            logger.warning(f"{name} returned None, using fallback")
            return fallback if fallback is not None else []
        return result
    except Exception as e:
        logger.error(f"{name} failed: {e}")
        return fallback if fallback is not None else []
