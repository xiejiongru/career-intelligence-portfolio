# ADR 0003: CI/CD Tag Strategy — Latest Only on Main

**Status**: Accepted
**Date**: 2026-10-10
**Deciders**: Pipeline Maintainer

## Context

Previous CI workflow pushed `:latest` tag on every build (including PRs). The cron scraper consumed `:latest` directly. This created risks:
- Unmerged PRs could pollute `:latest` with broken code
- Cron runs could fail due to in-progress PR changes
- No clear release boundary between "tested" and "experimental"

## Decision

Restructure CI to push `:latest` **only on main branch**:

### Build Job (`.github/workflows/ci.yml`)
```yaml
tags: |
  type=sha,prefix=sha-           # Always: sha-<commit>
  type=raw,value=latest,enable={{is_default_branch}}  # Only main
```

### CI Job Dependencies
- `lint`, `unit`, `contract` run on every push/PR
- `scraper-health` runs but `continue-on-error: true` (non-blocking)
- `run` job only triggers on `main` after `lint`, `unit`, `contract` pass

### Cron Workflow (`.github/workflows/scraper-cron.yml`)
- Consumes `ghcr.io/org/repo:latest` (guaranteed to be from main)
- Runs every 2 days independently of CI

## Consequences

### Positive
- Cron always runs known-good code from main
- PRs can't break scheduled scrapes
- Clear semantic: `latest` = "last passed CI on main"
- SHA tags provide immutable traceability

### Negative
- Main branch merges required to update `:latest`
- Hotfixes need fast-track merge to main

## Implementation

- `.github/workflows/ci.yml` — Restructured with metadata-action for conditional tags
- `.github/workflows/scraper-cron.yml` — Confirmed safe usage

## References

- [CI Workflow](../.github/workflows/ci.yml)
- [Cron Workflow](../.github/workflows/scraper-cron.yml)