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

Restructure CI to push `:latest` **only on the default branch**:

### Build Job (`.github/workflows/ci.yml`)
```yaml
tags: |
  type=sha,prefix=sha-           # Always: sha-<commit>
  type=raw,value=latest,enable={{is_default_branch}}  # Only the default branch
```

### CI Job Dependencies
- `lint`, `unit`, `contract` run on every push/PR
- `run` job only triggers on `master` after `lint`, `unit`, `contract` pass

### Cron Workflow (private runtime repo: `.github/workflows/scraper-cron.yml`)
- Consumes `ghcr.io/org/repo:latest` (guaranteed to be from the default branch)
- Runs every 2 days independently of CI

## Consequences

### Positive
- Cron always runs known-good code from the default branch
- PRs can't break scheduled scrapes
- Clear semantic: `latest` = "last passed CI on the default branch"
- SHA tags provide immutable traceability

### Negative
- Main branch merges required to update `:latest`
- Hotfixes need fast-track merge to main

## Implementation

- `.github/workflows/ci.yml` — Restructured with metadata-action for conditional tags
- Cron workflow lives in the private runtime repo and consumes only `ghcr.io/...:latest`

## References

- [CI Workflow](../../.github/workflows/ci.yml)
