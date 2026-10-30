# ADR 0002: Deterministic Job ID Generation Algorithm

**Status**: Accepted
**Date**: 2026-10-10
**Deciders**: Pipeline Maintainer

## Context

Previous scrapers generated job IDs using unreliable methods:
- Loop counters: `custom-{count}`, `seekau-{i}`
- Python's `hash()`: `custom-{hash(title)}` (randomized per process)
- No cross-run stability

This made it impossible to:
- Deduplicate across pipeline runs
- Track job updates (salary changes, description edits)
- Build historical analytics

## Decision

Implement a three-tier deterministic job ID algorithm in `generate_job_id()`:

### Priority 1: Source + Source Job ID
```
Format: {source}.{sanitized_source_job_id}
Example: greenhouse.456789
```
Used when the source provides a stable ID (ATS platforms, platform boards, etc.)

### Priority 2: Source + Canonical URL Hash
```
Format: {source}.url.{sha256(netloc+path)[:16]}
Example: indeed.url.21548823e2eea3cb
```
Used when no source_job_id but URL is available and stable.

### Priority 3: Source + Content Hash
```
Format: {source}.content.{sha256(title|company|location)[:16]}
Example: georezo.content.a1b2c3d4e5f67890
```
Fallback when neither source ID nor URL is reliable.

### Constraints
- Lowercase alphanumeric + `._-` only
- Max 128 characters
- Source prefix enables partitioning

## Consequences

### Positive
- Same job → same ID across all pipeline runs
- Different jobs → different IDs (SHA-256 collision resistance)
- No external state required (pure function)
- Enables reliable JSONL deduplication

### Negative
- Content hash fallback changes if title/company/location normalizes differently
- URL hash changes if canonical URL structure changes
- Source_job_id must be stable (some ATS reuse IDs)

## Mitigations
- Normalization happens before ID generation (stable company/location names)
- URL cleaning removes tracking params before hashing
- Priority order prefers most stable identifiers

## Implementation

- `pipeline/output/job_record.py::generate_job_id()`
- Used in `JobRecord.from_job_posting()` and `_convert_to_job_records()`
- Tests in `tests/test_job_record.py::TestGenerateJobId`

## References

- [FIELD_SOURCE_MATRIX.md](../../pipeline/output/FIELD_SOURCE_MATRIX.md#deterministic-job-id-algorithm)