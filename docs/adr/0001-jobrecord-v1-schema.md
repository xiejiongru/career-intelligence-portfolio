# ADR 0001: JobRecord v1 Schema Design

**Status**: Accepted
**Date**: 2026-10-10
**Deciders**: Pipeline Maintainer

## Context

The job pipeline previously used an in-memory `JobPosting` dataclass with dynamic attributes added at each stage. This approach had several limitations:

1. **No stable identity**: Scrapers generated IDs using loop counters or Python's `hash()`, making cross-run deduplication unreliable
2. **No change detection**: Could not distinguish new jobs from updated postings
3. **No audit trail**: Missing `first_seen_at`, `last_seen_at`, `published_at` timestamps
4. **Schema drift**: Fields added ad-hoc without versioning or validation
5. **No separation of concerns**: Analysis results mixed with raw job data

## Decision

Adopt a versioned JSON Schema (`JobRecord v1`) as the canonical data contract with:

- **Stable `job_id`**: Three-tier deterministic generation (source_job_id → canonical_url → content_hash)
- **Content hash**: SHA-256 of normalized (title|company|location|description) for change detection
- **ISO 8601 UTC timestamps**: `discovered_at`, `first_seen_at`, `last_seen_at`, `published_at`
- **Structured analysis**: Separate `hard_filter`, `screening`, `ranking` objects with version metadata
- **Enum constraints**: `employment_type`, `remote`, `status` restricted to known values
- **Null for unknowns**: Use `null` instead of empty strings or fabricated values

## Consequences

### Positive
- Reliable cross-run deduplication and update detection
- Full audit trail for each job posting
- Schema validation prevents silent data corruption
- Clear separation between raw data and analysis
- Enables Vault integration and historical analysis

### Negative
- Migration effort from legacy `JobPosting` format
- More verbose JSON output (mitigated by JSONL storage)
- Schema evolution requires version management

## Implementation

- `pipeline/output/job_record_schema.json` — JSON Schema Draft-07
- `pipeline/output/job_record.py` — Python dataclass with validation, `from_job_posting()` converter
- `pipeline/utils/entity_resolver.py` — Normalization (company, location, job_type, remote, URL)
- `pipeline/output/FIELD_SOURCE_MATRIX.md` — Field provenance documentation

## References

- [FIELD_SOURCE_MATRIX.md](../../pipeline/output/FIELD_SOURCE_MATRIX.md)
- [JobRecord v1 JSON Schema](../../schemas/job-record-v1.json)