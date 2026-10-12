"""
Structured Logging with Failure Categorization for Job Pipeline.

Provides:
- Structured JSON logging for CI/CD consumption
- Failure categorization (network/parse/validation/rate-limit/auth/unknown)
- Run summary generation
- Context-aware loggers for each pipeline phase
"""
from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from contextlib import contextmanager


class FailureCategory(str, Enum):
    """Standardized failure categories for consistent error handling."""
    NETWORK = "network"          # Connection errors, timeouts, DNS failures
    PARSE = "parse"              # HTML/JSON parsing errors, schema validation failures
    VALIDATION = "validation"    # Data validation failures (required fields, formats)
    RATE_LIMIT = "rate_limit"    # HTTP 429, rate limiting responses
    AUTH = "auth"                # Authentication/authorization failures
    CONFIG = "config"            # Configuration errors (missing keys, invalid values)
    UNKNOWN = "unknown"          # Unclassified failures


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class StructuredLogRecord:
    """Structured log record for JSON output."""
    timestamp: str
    level: str
    logger: str
    message: str
    phase: Optional[str] = None
    source: Optional[str] = None
    job_id: Optional[str] = None
    failure_category: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: Optional[float] = None
    metadata: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_record = StructuredLogRecord(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            level=record.levelname,
            logger=record.name,
            message=record.getMessage(),
            phase=getattr(record, "phase", None),
            source=getattr(record, "source", None),
            job_id=getattr(record, "job_id", None),
            failure_category=getattr(record, "failure_category", None),
            error_type=getattr(record, "error_type", None),
            error_message=getattr(record, "error_message", None),
            duration_ms=getattr(record, "duration_ms", None),
            metadata=getattr(record, "metadata", {}),
        )
        return log_record.to_json()


class PipelineLogger:
    """Context-aware logger for pipeline phases."""

    def __init__(self, name: str, phase: Optional[str] = None):
        self.logger = logging.getLogger(name)
        self.phase = phase

    def _log(self, level: LogLevel, message: str, **kwargs) -> None:
        extra = {
            "phase": self.phase,
            **kwargs,
        }
        self.logger.log(level.value, message, extra=extra)

    def debug(self, message: str, **kwargs) -> None:
        self._log(LogLevel.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs) -> None:
        self._log(LogLevel.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        self._log(LogLevel.WARNING, message, **kwargs)

    def error(self, message: str, failure_category: FailureCategory = FailureCategory.UNKNOWN, **kwargs) -> None:
        self._log(LogLevel.ERROR, message, failure_category=failure_category.value, **kwargs)

    def critical(self, message: str, failure_category: FailureCategory = FailureCategory.UNKNOWN, **kwargs) -> None:
        self._log(LogLevel.CRITICAL, message, failure_category=failure_category.value, **kwargs)

    @contextmanager
    def timed(self, operation: str, **kwargs) -> Any:
        """Context manager for timing operations."""
        start = time.monotonic()
        self.info(f"Starting {operation}", **kwargs)
        try:
            yield
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            self.error(
                f"Failed {operation}: {e}",
                error_type=type(e).__name__,
                error_message=str(e),
                duration_ms=duration_ms,
                **kwargs,
            )
            raise
        else:
            duration_ms = (time.monotonic() - start) * 1000
            self.info(f"Completed {operation}", duration_ms=duration_ms, **kwargs)


def categorize_exception(exc: Exception) -> FailureCategory:
    """Categorize an exception into a standard failure category."""
    exc_type = type(exc).__name__
    exc_msg = str(exc).lower()

    # Network errors
    if exc_type in ("ConnectionError", "TimeoutError", "ConnectTimeout", "ReadTimeout"):
        return FailureCategory.NETWORK
    if any(kw in exc_msg for kw in ["connection refused", "connection reset", "dns", "timeout", "unreachable"]):
        return FailureCategory.NETWORK

    # Rate limiting
    if exc_type in ("TooManyRequests", "RateLimitError"):
        return FailureCategory.RATE_LIMIT
    if any(kw in exc_msg for kw in ["429", "rate limit", "too many requests", "throttle"]):
        return FailureCategory.RATE_LIMIT

    # Auth errors
    if exc_type in ("AuthenticationError", "PermissionError", "Unauthorized"):
        return FailureCategory.AUTH
    if any(kw in exc_msg for kw in ["401", "403", "unauthorized", "forbidden", "auth"]):
        return FailureCategory.AUTH

    # Parse errors
    if exc_type in ("JSONDecodeError", "ParseError", "XMLSyntaxError", "HTMLParseError"):
        return FailureCategory.PARSE
    if any(kw in exc_msg for kw in ["parse", "decode", "malformed", "invalid json", "invalid html"]):
        return FailureCategory.PARSE

    # Validation errors
    if exc_type in ("ValidationError", "ValueError", "TypeError", "KeyError"):
        return FailureCategory.VALIDATION
    if any(kw in exc_msg for kw in ["validation", "required field", "missing field", "invalid format"]):
        return FailureCategory.VALIDATION

    # Config errors
    if exc_type in ("ConfigError", "ConfigurationError"):
        return FailureCategory.CONFIG
    if any(kw in exc_msg for kw in ["config", "setting", "environment variable", "missing key"]):
        return FailureCategory.CONFIG

    return FailureCategory.UNKNOWN


@dataclass
class PhaseMetrics:
    """Metrics for a single pipeline phase."""
    phase: str
    started_at: str
    completed_at: Optional[str] = None
    duration_ms: Optional[float] = None
    input_count: int = 0
    output_count: int = 0
    error_count: int = 0
    errors_by_category: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class RunSummary:
    """Complete pipeline run summary."""
    run_id: str
    started_at: str
    completed_at: Optional[str] = None
    duration_ms: Optional[float] = None
    status: str = "running"  # running, success, failed, partial
    phases: list[PhaseMetrics] = field(default_factory=list)
    total_jobs_scraped: int = 0
    total_jobs_normalized: int = 0
    total_jobs_filtered: int = 0
    total_jobs_ranked: int = 0
    total_job_records: int = 0
    new_records: int = 0
    updated_records: int = 0
    vault_exports: int = 0
    errors: list[dict] = field(default_factory=list)

    def add_phase(self, metrics: PhaseMetrics) -> None:
        self.phases.append(metrics)

    def add_error(self, phase: str, category: FailureCategory, error_type: str, message: str, **context) -> None:
        self.errors.append({
            "phase": phase,
            "category": category.value,
            "error_type": error_type,
            "message": message,
            "context": context,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        })

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        """Generate human-readable markdown summary."""
        lines = [
            "# Pipeline Run Summary",
            "",
            f"**Run ID:** {self.run_id}",
            f"**Status:** {self.status}",
            f"**Started:** {self.started_at}",
        ]
        if self.completed_at:
            lines.append(f"**Completed:** {self.completed_at}")
        if self.duration_ms:
            lines.append(f"**Duration:** {self.duration_ms / 1000:.1f}s")
        lines.append("")

        lines.append("## Phase Metrics")
        lines.append("| Phase | Duration (ms) | Input | Output | Errors |")
        lines.append("|-------|---------------|-------|--------|--------|")
        for p in self.phases:
            lines.append(f"| {p.phase} | {p.duration_ms or 'N/A'} | {p.input_count} | {p.output_count} | {p.error_count} |")
        lines.append("")

        lines.append("## Totals")
        lines.append(f"- Jobs Scraped: {self.total_jobs_scraped}")
        lines.append(f"- Jobs Normalized: {self.total_jobs_normalized}")
        lines.append(f"- Jobs Passed Filter: {self.total_jobs_filtered}")
        lines.append(f"- Jobs Ranked: {self.total_jobs_ranked}")
        lines.append(f"- JobRecords Created: {self.total_job_records}")
        lines.append(f"- New Records: {self.new_records}")
        lines.append(f"- Updated Records: {self.updated_records}")
        lines.append(f"- Vault Exports: {self.vault_exports}")
        lines.append("")

        if self.errors:
            lines.append("## Errors")
            lines.append("| Phase | Category | Type | Message |")
            lines.append("|-------|----------|------|---------|")
            for e in self.errors:
                lines.append(f"| {e['phase']} | {e['category']} | {e['error_type']} | {e['message']} |")
        else:
            lines.append("## Errors")
            lines.append("No errors.")

        return "\n".join(lines)


def setup_structured_logging(
    level: int = logging.INFO,
    json_output: bool = False,
    log_file: Optional[str] = None,
) -> None:
    """Configure structured logging for the pipeline."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    if json_output:
        console_handler.setFormatter(StructuredFormatter())
    else:
        console_handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(file_handler)


def get_pipeline_logger(name: str, phase: Optional[str] = None) -> PipelineLogger:
    """Get a pipeline logger for the given component."""
    return PipelineLogger(name, phase)
