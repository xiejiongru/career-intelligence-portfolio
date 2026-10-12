"""
JobRecord v1 — Canonical normalized job record for Career Intelligence Pipeline.

This module provides:
- JobRecord dataclass with validation
- Conversion from JobPosting (ingestion model) to JobRecord
- JSON Schema validation
- Deterministic job_id generation
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from jsonschema import Draft7Validator

from pipeline.ingestion.models import JobPosting
from pipeline.utils.entity_resolver import (
    clean_url,
    normalize_company_name,
    normalize_job_type,
    normalize_location,
    normalize_remote,
)

SCHEMA_VERSION = "1.0.0"

VALID_SOURCES = frozenset([
    "linkedin", "indeed", "georezo", "greenhouse", "lever", "smartrecruiters",
    "tomtom", "esri", "edf", "schneider", "totalenergies", "wttj",
    "seekau", "jobat", "oikotie", "iamexpat", "jobslu",
    "capgemini", "magellium", "cgi", "aae_ensg",
])

VALID_EMPLOYMENT_TYPES = frozenset([
    "CDI", "CDD", "Stage", "Alternance", "Apprentissage", "Freelance", "VIE", "Part-time", "Contract"
])

VALID_REMOTE = frozenset(["Yes", "Partial", "No"])

VALID_STATUS = frozenset(["active", "closed", "expired", "filled", "unknown"])

JOB_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
ISO8601_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$"
)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_iso8601(value: str, field_name: str) -> None:
    if not ISO8601_PATTERN.match(value):
        raise ValueError(f"{field_name} must be ISO 8601 UTC (e.g., 2026-10-10T12:34:56Z), got: {value}")


def _validate_sha256(value: str, field_name: str) -> None:
    if not SHA256_PATTERN.match(value):
        raise ValueError(f"{field_name} must be 64-char lowercase hex SHA-256, got: {value}")


def _validate_job_id(value: str) -> None:
    if not JOB_ID_PATTERN.match(value):
        raise ValueError(f"job_id must match ^[a-z0-9][a-z0-9._-]{{0,127}}$, got: {value}")


def _validate_enum(value: str, valid_set: frozenset[str], field_name: str) -> None:
    if value not in valid_set:
        raise ValueError(f"{field_name} must be one of {sorted(valid_set)}, got: {value}")


@dataclass(frozen=True)
class HardFilterAnalysis:
    passed: bool
    reasons: list[str]
    missing_skills: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ScreeningAnalysis:
    decision: str
    score: float
    filtered: bool
    filter_reasons: list[str]
    seniority: str
    match_scores: dict[str, float]
    skills: dict[str, list[str]]
    gap_analysis: dict[str, list[str]]
    summary: str
    rules_version: str
    model_version: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RankingAnalysis:
    final_score: float
    thinking_trace: str
    kernel_version: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class JobRecordAnalysis:
    hard_filter: HardFilterAnalysis
    screening: Optional[ScreeningAnalysis]
    ranking: Optional[RankingAnalysis]

    def to_dict(self) -> dict:
        return {
            "hard_filter": self.hard_filter.to_dict(),
            "screening": self.screening.to_dict() if self.screening else None,
            "ranking": self.ranking.to_dict() if self.ranking else None,
        }


@dataclass(frozen=True)
class JobRecord:
    schema_version: str
    job_id: str
    source: str
    source_job_id: Optional[str]
    canonical_url: str
    title: str
    company: str
    location: str
    employment_type: Optional[str]
    remote: Optional[str]
    salary: Optional[str]
    description: str
    published_at: Optional[str]
    discovered_at: str
    first_seen_at: str
    last_seen_at: str
    content_hash: str
    status: str
    normalization_warnings: Optional[list[str]]
    analysis: Optional[JobRecordAnalysis]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION}, got {self.schema_version}")
        _validate_job_id(self.job_id)
        if self.source not in VALID_SOURCES:
            raise ValueError(f"source must be one of {sorted(VALID_SOURCES)}, got: {self.source}")
        if self.source_job_id is not None and not isinstance(self.source_job_id, str):
            raise ValueError("source_job_id must be string or null")
        _validate_iso8601(self.discovered_at, "discovered_at")
        _validate_iso8601(self.first_seen_at, "first_seen_at")
        _validate_iso8601(self.last_seen_at, "last_seen_at")
        _validate_sha256(self.content_hash, "content_hash")
        _validate_enum(self.status, VALID_STATUS, "status")
        if self.employment_type is not None:
            _validate_enum(self.employment_type, VALID_EMPLOYMENT_TYPES, "employment_type")
        if self.remote is not None:
            _validate_enum(self.remote, VALID_REMOTE, "remote")
        if self.published_at is not None:
            _validate_iso8601(self.published_at, "published_at")
        if self.normalization_warnings is not None:
            if not isinstance(self.normalization_warnings, list):
                raise ValueError("normalization_warnings must be list or null")
            for w in self.normalization_warnings:
                if not isinstance(w, str):
                    raise ValueError("normalization_warnings items must be strings")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "source": self.source,
            "source_job_id": self.source_job_id,
            "canonical_url": self.canonical_url,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "employment_type": self.employment_type,
            "remote": self.remote,
            "salary": self.salary,
            "description": self.description,
            "published_at": self.published_at,
            "discovered_at": self.discovered_at,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "content_hash": self.content_hash,
            "status": self.status,
            "normalization_warnings": self.normalization_warnings,
            "analysis": self.analysis.to_dict() if self.analysis else None,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_job_posting(
        cls,
        job: JobPosting,
        source: str,
        source_job_id: Optional[str] = None,
        published_at: Optional[str] = None,
        status: str = "active",
        hard_filter_passed: bool = True,
        hard_filter_reasons: Optional[list[str]] = None,
        missing_skills: Optional[list[str]] = None,
        screening_results: Optional[dict] = None,
        ranking_result: Optional[dict] = None,
        rules_version: str = "1.0",
        model_version: str = "1.0",
        kernel_version: str = "1.0",
        existing_record: Optional["JobRecord"] = None,
        warnings: Optional[list[str]] = None,
    ) -> "JobRecord":
        """
        Create a JobRecord from a JobPosting with all pipeline analysis results.

        Args:
            job: The raw JobPosting from ingestion
            source: Source identifier (must be in VALID_SOURCES)
            source_job_id: Original job ID from source, if available
            published_at: Original publication date from source (ISO 8601)
            status: Job status (active/closed/expired/filled/unknown)
            hard_filter_passed: Whether job passed hard filter
            hard_filter_reasons: List of hard filter failure reasons
            missing_skills: Skills missing per hard filter
            screening_results: Dict from FranceGeoJobScreener.screen()
            ranking_result: Dict from ThinkingKernel.evaluate()
            rules_version: Version of screening rules
            model_version: Version of LLM model used
            kernel_version: Version of thinking kernel
            existing_record: Previous JobRecord if this is an update (for first_seen_at)
            warnings: Normalization warnings collected during cleaning
        """
        now = _now_utc()
        first_seen = existing_record.first_seen_at if existing_record else now
        last_seen = now

        # Normalize fields
        clean_company = normalize_company_name(job.company)
        clean_location = normalize_location(job.location)
        clean_job_type = normalize_job_type(job.job_type)
        clean_remote = normalize_remote(job.remote)
        clean_job_url = clean_url(job.url)
        clean_title = re.sub(r"\s+", " ", job.title.strip()) if job.title else "Unknown"
        clean_desc = job.description.strip() if job.description else ""

        # Compute content hash for change detection
        content_for_hash = f"{clean_title}|{clean_company}|{clean_location}|{clean_desc}"
        content_hash = hashlib.sha256(content_for_hash.encode("utf-8")).hexdigest()

        # Generate deterministic job_id
        job_id = generate_job_id(
            source=source,
            source_job_id=source_job_id,
            canonical_url=clean_job_url,
            title=clean_title,
            company=clean_company,
            location=clean_location,
        )

        # Build analysis objects
        hf_analysis = HardFilterAnalysis(
            passed=hard_filter_passed,
            reasons=hard_filter_reasons or [],
            missing_skills=missing_skills or [],
        )

        screening_analysis = None
        if screening_results:
            ms = screening_results.get("match_scores", {})
            skills = screening_results.get("skills", {})
            gap = screening_results.get("gap_analysis", {})
            screening_analysis = ScreeningAnalysis(
                decision=screening_results.get("decision", "unknown"),
                score=float(screening_results.get("score", 0)),
                filtered=screening_results.get("filtered", False),
                filter_reasons=screening_results.get("filter_reasons", []),
                seniority=screening_results.get("seniority", ""),
                match_scores={
                    "tech_match": float(ms.get("tech_match", 0)),
                    "function_match": float(ms.get("function_match", 0)),
                    "domain_match": float(ms.get("domain_match", 0)),
                    "experience_match": float(ms.get("experience_match", 0)),
                    "growth_potential": float(ms.get("growth_potential", 0)),
                },
                skills={
                    "gis": skills.get("gis", []),
                    "data": skills.get("data", []),
                    "devops": skills.get("devops", []),
                    "programming": skills.get("programming", []),
                },
                gap_analysis={
                    "missing_skills": gap.get("missing_skills", []),
                    "risk_factors": gap.get("risk_factors", []),
                    "leverage_points": gap.get("leverage_points", []),
                },
                summary=screening_results.get("summary", ""),
                rules_version=rules_version,
                model_version=model_version,
            )

        ranking_analysis = None
        if ranking_result:
            ranking_analysis = RankingAnalysis(
                final_score=float(ranking_result.get("final_score", 0)),
                thinking_trace=ranking_result.get("thinking_trace", ""),
                kernel_version=kernel_version,
            )

        analysis = JobRecordAnalysis(
            hard_filter=hf_analysis,
            screening=screening_analysis,
            ranking=ranking_analysis,
        )

        return cls(
            schema_version=SCHEMA_VERSION,
            job_id=job_id,
            source=source,
            source_job_id=source_job_id,
            canonical_url=clean_job_url,
            title=clean_title,
            company=clean_company,
            location=clean_location,
            employment_type=clean_job_type,
            remote=clean_remote,
            salary=job.salary.strip() if job.salary else None,
            description=clean_desc,
            published_at=published_at,
            discovered_at=now,
            first_seen_at=first_seen,
            last_seen_at=last_seen,
            content_hash=content_hash,
            status=status,
            normalization_warnings=warnings,
            analysis=analysis,
        )


def generate_job_id(
    source: str,
    source_job_id: Optional[str],
    canonical_url: str,
    title: str,
    company: str,
    location: str,
) -> str:
    """
    Generate a stable, deterministic job_id.

    Priority:
    1. source + source_job_id (if source_job_id is stable and available)
    2. canonical_url (normalized URL without tracking params)
    3. SHA-256 of normalized (title + company + location) — last resort

    All outputs are lowercased, alphanumeric + ._- only, max 128 chars.
    """
    # Strategy 1: source + source_job_id
    if source_job_id and source_job_id.strip():
        # Sanitize source_job_id: keep alphanumeric, . _ -
        sanitized = re.sub(r"[^a-zA-Z0-9._-]", "_", source_job_id.strip().lower())
        candidate = f"{source}.{sanitized}"
        if JOB_ID_PATTERN.match(candidate) and len(candidate) <= 128:
            return candidate

    # Strategy 2: canonical_url
    if canonical_url:
        parsed = urlparse(canonical_url)
        # Use netloc + path as base
        url_base = f"{parsed.netloc}{parsed.path}"
        # Hash it for stable length
        url_hash = hashlib.sha256(url_base.encode("utf-8")).hexdigest()[:16]
        candidate = f"{source}.url.{url_hash}"
        if JOB_ID_PATTERN.match(candidate):
            return candidate

    # Strategy 3: content hash (title + company + location)
    content = f"{title}|{company}|{location}".lower()
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    candidate = f"{source}.content.{content_hash}"
    if JOB_ID_PATTERN.match(candidate):
        return candidate

    # Fallback (should never happen)
    fallback = hashlib.sha256(f"{source}|{title}|{company}|{location}".encode("utf-8")).hexdigest()[:16]
    return f"{source}.fallback.{fallback}"


def validate_job_record(record: dict) -> list[str]:
    """
    Validate a JobRecord dict against the JSON Schema.
    Returns list of error messages (empty if valid).
    """
    with open("pipeline/output/job_record_schema.json", "r", encoding="utf-8") as f:
        schema = json.load(f)

    validator = Draft7Validator(schema)
    errors = list(validator.iter_errors(record))
    return [f"{'.'.join(str(p) for p in e.path)}: {e.message}" for e in errors]


def job_record_to_jsonl(record: JobRecord) -> str:
    """Serialize JobRecord to a single JSONL line."""
    return json.dumps(record.to_dict(), ensure_ascii=False)
