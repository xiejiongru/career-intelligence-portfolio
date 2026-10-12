# ADR 0004: Privacy Boundary — Private Vault vs Public Portfolio

**Status**: Accepted
**Date**: 2026-10-09 (Phase 0), confirmed 2026-10-10
**Deciders**: Pipeline Maintainer

## Context

Two distinct systems exist:
1. **Job Pipeline** (`D:\work\job-pipeline`) — Code, schema, fixtures, tests (can be public)
2. **Career Second Brain / prof-vault** (`D:\prof`) — Personal CV, raw conversations, interview notes, company research, application tracking (MUST remain private)

Risk: Accidental exposure of private career data in public repositories.

## Decision

Enforce strict separation with three tiers:

### Tier 1: Public Portfolio (`career-intelligence-portfolio/`)
- **Contents**: Schema, processing code (sanitized), demo fixtures, architecture docs, ADRs, README
- **No PII**: No real company names, salaries, contact info, personal analysis
- **Purpose**: Showcase engineering, enable reproducibility, attract collaborators

### Tier 2: Job Pipeline Runtime Data (`job-pipeline/data/`, `output/`, `artifacts/`)
- **Contents**: Real scraped jobs, JSONL store, Vault exports, run summaries, metrics
- **Gitignored**: `data/`, `output/`, `artifacts/`, `*.log` in `.gitignore`
- **Purpose**: Local pipeline operation, historical tracking

### Tier 3: Career Second Brain (`D:\prof/`)
- **Contents**: CV, conversations, interview transcripts, company deep-dives, application tracker, personal reflections
- **Never synced**: No automated export from pipeline to vault
- **Manual bridge**: Vault imports `data/for_vault/*.json` manually to create Markdown Job Cards

## Data Flow Rules

```
Job Sources → Pipeline → data/job_records.jsonl (Tier 2, gitignored)
                          ↓
              data/for_vault/{job_id}.json (Tier 2, gitignored)
                          ↓ (manual copy)
              prof-vault/Jobs/{company}/{role}.md (Tier 3, private)
```

### Prohibited
- ❌ Copying `D:\prof` content to any public repo
- ❌ Committing real scraped data to public repo
- ❌ Committing real CV, salaries, contacts, interview notes
- ❌ Automated sync from pipeline to vault (preserves human agency)

### Required
- ✅ `.gitignore` excludes `data/`, `output/`, `artifacts/`, `output/runs/`
- ✅ Public repo uses only sanitized demo fixtures
- ✅ Schema/docs/code in public repo contain no real-world PII
- ✅ Human reviews each Vault import

## Consequences

### Positive
- Zero risk of PII leakage to public GitHub
- Clear ownership: pipeline = code/data processing, vault = human decisions
- Manual bridge ensures intentionality in job applications

### Negative
- Manual step required for Vault import
- No automated "apply with one click" (intentional)

## Implementation

- `job-pipeline/.gitignore` — Excludes `data/`, `output/`, `artifacts/`, `output/runs/`
- `career-intelligence-portfolio/data/demo/` — Only sanitized fixtures
- `docs/adr/0004-privacy-boundary.md` — This document

## References

- [JobRecord v1 Schema](../../schemas/job-record-v1.json) — No PII fields
