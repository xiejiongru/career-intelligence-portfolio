"""Structured scraper error codes with retryable flag (actionbook pattern)."""


class ScraperError(Exception):
    """Base error with machine-readable code and retryable flag."""
    def __init__(self, code: str, message: str, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class BlockedError(ScraperError):
    """Site actively blocking (geo-block, captcha, Radware, Cloudflare, rate-limit)."""
    def __init__(self, site: str, block_type: str):
        super().__init__(
            code=f"BLOCKED_{block_type.upper()}",
            message=f"{site}: {block_type}",
            retryable=False,
        )


class TransientError(ScraperError):
    """Temporary failure that may succeed on retry (timeout, connection reset, 5xx)."""
    def __init__(self, site: str, cause: str):
        super().__init__(
            code="TRANSIENT",
            message=f"{site}: {cause}",
            retryable=True,
        )


class ParseError(ScraperError):
    """Content fetched but couldn't be parsed (selector not found, unexpected structure)."""
    def __init__(self, site: str, detail: str):
        super().__init__(
            code="PARSE_FAILED",
            message=f"{site}: {detail}",
            retryable=False,
        )
