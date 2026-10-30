# ADR 0005: Test Strategy — Offline Unit/Contract vs Online Health Checks

**Status**: Accepted
**Date**: 2026-10-10
**Deciders**: Pipeline Maintainer

> **Public snapshot note:** the `scraper-health` job is not part of this repository. Live-site checks are maintained in the private pipeline; the public CI runs only the blocking offline tiers.

## Context

Previous test suite mixed:
- Fast, deterministic unit tests (fixtures only)
- Slow, flaky scraper integration tests (real HTTP requests)
- No clear separation in CI

Problems:
- CI flakiness due to external site changes/rate limits
- Slow feedback loop (>10 min for full suite)
- Couldn't distinguish "code broken" from "site changed"
- No contract validation for data schemas

## Decision

Three-tier test architecture with clear CI boundaries:

### Tier 1: Unit Tests (Offline, Fixtures Only) — **Blocking**
- **Scope**: Pure functions, no I/O
- **Targets**: `hard_filter`, `ranker`, `thinking_kernel`, `entity_resolver`, `schemas`
- **Data**: Fixed fixtures in `tests/fixtures/`
- **CI**: `unit` job — must pass on every push/PR
- **Time**: <30 seconds

### Tier 2: Contract Tests (Schema Validation) — **Blocking**
- **Scope**: Data contracts, serialization round-trips
- **Targets**: `JobRecord` JSON Schema validation, Entity Resolver fixtures
- **Data**: `tests/fixtures/job_records/*.json`
- **CI**: `contract` job — must pass on every push/PR
- **Time**: <15 seconds

### Tier 3: Live Scraper Checks (Private Pipeline) — **Not in Public CI**
- **Scope**: End-to-end scraper integration
- **Targets**: Private employer-specific adapters and public adapters
- **Data**: Live websites
- **CI**: Private pipeline only; not part of this snapshot
- **Time**: 2-5 minutes
- **Alerting**: Failure creates a GitHub Issue in the private pipeline

### Tier 4: Cron Pipeline (Production) — **Manual/Scheduled**
- **Scope**: Full pipeline with real data
- **Trigger**: Schedule (every 2 days) or `workflow_dispatch`
- **Artifacts**: 30-day retention
- **Alerting**: Failure creates GitHub Issue

## Test Data Policy

| Test Type | Data Source | Network | Deterministic |
|-----------|-------------|---------|---------------|
| Unit | Fixtures | No | Yes |
| Contract | Fixtures | No | Yes |
| Live Checks (private) | Live Sites | Yes | No (best effort) |
| Cron | Live Sites | Yes | N/A |

## Consequences

### Positive
- Fast, reliable CI feedback (<1 min for blocking jobs)
- Clear signal: unit/contract failure = code bug
- Contract tests catch schema drift early
- Live checks stay in the private pipeline and never block public CI

### Negative
- Live-site regressions are not covered by the public CI
- Requires maintaining fixture parity with real responses

## Mitigations
- Private live checks create GitHub Issues in the private pipeline
- Fixtures updated when scraper contracts change
- Private cron runs provide production validation every 48h

## Implementation

- `.github/workflows/ci.yml` — blocking lint, unit and contract jobs
- `tests/test_job_record.py::TestValidateJobRecord` — Contract tests
- `tests/test_entity_resolver.py` — Fixture-based normalization tests
- Live checks are maintained in the private pipeline and are not published.

## References

- [CI Workflow](../../.github/workflows/ci.yml)
