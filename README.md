# Career Intelligence Portfolio

AI-native career intelligence pipeline — scrapes, filters, screens, and ranks job postings, then exports them as a versioned, validated **JobRecord v1** JSON contract.

Public snapshot of the pipeline: schema, sanitized demo data, architecture diagrams, ADRs, and CI. Private configuration, real run data, and candidate information are excluded by design (see [ADR 0004](docs/adr/0004-privacy-boundary.md)).

> **En bref (FR)** — Pipeline de talent intelligence : les offres issues de 21 sources (agrégateurs, API ATS, sites carrières) sont normalisées et dédupliquées dans un contrat de données versionné (JobRecord v1). Chaque annonce conserve le même identifiant d'une collecte à l'autre, les modifications de contenu sont détectées, et chaque décision de présélection reste traçable. Les données publiées sont assainies ; aucune donnée personnelle n'est incluse. Résumé pas à pas : [étude de cas (FR)](docs/case-study.fr.md).

## Why this matters

Job postings are one of the most current public signals of what a company is building, where it is hiring, and which skills it is short of. In practice that signal is fragmented: aggregators, ATS APIs, career sites, and niche job boards each use their own IDs, company names, location formats, and contract labels. Reposts create duplicates, edited descriptions overwrite history, and missing fields get guessed.

This project treats job postings as **data with a contract**, not as pages to read. The same posting keeps the same identity across runs, changes are detectable, every field has a recorded source, and unknown values stay `null` instead of being invented. For a team, that means less manual de-duplication, screening decisions that can be audited line by line, and a dataset that can be reused for market analysis instead of rebuilt for every campaign.

### What a team gets

| Operational need | What the pipeline provides | Where |
|---|---|---|
| One dataset across many sources | The private pipeline covers 21 sources; this snapshot ships generic adapters for 11 source types (aggregators, ATS APIs, platform boards, a GIS board) | `pipeline/ingestion/`, [field source matrix](pipeline/output/FIELD_SOURCE_MATRIX.md) |
| No duplicates on re-runs | Deterministic `job_id` (three-tier fallback) + job_id-keyed JSONL store | [ADR 0002](docs/adr/0002-deterministic-job-id.md) |
| Detect edited or reposted jobs | SHA-256 `content_hash` over title, company, location, and description | JobRecord v1 |
| Explainable shortlisting | Hard filter, 5-dimension screening, and 4-layer ranking stored as separate, auditable blocks | `pipeline/matching/`, [architecture](docs/architecture.md) |
| Safe use of real data | Sanitized demos only; private config and candidate data excluded by design | [ADR 0004](docs/adr/0004-privacy-boundary.md) |
| Data quality enforced in CI | Schema validation, offline unit tests, contract tests, pinned lint rules | [CI](.github/workflows/ci.yml), [ADR 0005](docs/adr/0005-test-strategy.md) |

Trace one demo record from raw source fields to stored output: [case study](docs/case-study.md).

### Where it is relevant

- **Talent intelligence and labor-market analytics** — standardized records with `first_seen_at` / `last_seen_at` support measuring skill demand, contract-type mix, and posting churn over time, not just a one-off snapshot.
- **HR tech and ATS integrations** — stable IDs plus content hashes are the mechanism needed to sync external job boards into an ATS without duplicates or silent overwrites.
- **Energy, engineering, and geospatial employers** — the private source set targets the French industrial and geospatial job market; employer-specific adapters are anonymized in this snapshot.
- **AI / LLM data pipelines** — explicit `null`s, field-level provenance, and a versioned schema make the records usable as structured input for retrieval and analysis instead of scraping prose at query time.

### What is reusable

The [JobRecord v1 schema](schemas/job-record-v1.json), the [field provenance matrix](pipeline/output/FIELD_SOURCE_MATRIX.md), and the [privacy boundary](docs/adr/0004-privacy-boundary.md) are standalone artifacts. A team can adopt the contract, the change-detection pattern, or the privacy model without adopting the scrapers.

> **Scope note:** this is a public snapshot, not a hosted service. Live scraping depends on third-party sites; this repo runs only offline lint, unit, contract and demo-validation jobs. All demo data is sanitized.

## What's inside

| Path | Contents |
|---|---|
| `schemas/job-record-v1.json` | JobRecord v1 JSON Schema (Draft-07) — canonical data contract |
| `pipeline/` | Pipeline code: ingestion, filtering, matching, output, utils |
| `pipeline/output/` | `JobRecord` dataclass, validation, deterministic `job_id`, field provenance matrix |
| `data/demo/` | 10 sanitized demo JobRecords (JSON + JSONL) |
| `tests/` | Offline unit tests + contract tests (schema, entity resolver fixtures) |
| `docs/architecture.md` | Mermaid diagrams of the end-to-end data flow |
| `docs/adr/` | Architecture Decision Records (schema, job_id, CI tags, privacy, test strategy) |

## Pipeline stages

```
Sources → Ingest → Normalize (entity resolution)
        → Filter (country, contract type, mandatory keywords)
        → Screen (5-dimension scoring → apply / maybe / skip)
        → Rank (ThinkingKernel: skills, domain, buzzword critique)
        → JobRecord v1 (deterministic id, content hash, audit trail)
        → JSONL store + Vault export
```

Details: [docs/architecture.md](docs/architecture.md).

## JobRecord v1

Every posting becomes a versioned record with:

- **Deterministic `job_id`** — `source_job_id` → `canonical_url` → `content_hash` (three-tier, ADR 0002)
- **`content_hash`** — SHA-256 of `title|company|location|description` for update detection
- **ISO 8601 UTC timestamps** — `first_seen_at`, `last_seen_at`, `published_at`
- **Structured analysis** — `hard_filter`, `screening`, `ranking` kept separate from raw data
- **`null` for unknowns** — never fabricated values

Validate any record:

```bash
pip install jsonschema
python -c "
import json, sys
from jsonschema import Draft7Validator
schema = json.load(open('schemas/job-record-v1.json'))
record = json.load(open('data/demo/job_record_demo_1.json'))
errs = list(Draft7Validator(schema).iter_errors(record))
print('OK' if not errs else errs)
sys.exit(1 if errs else 0)
"
```

## Development

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# Lint (explicit rule set in ruff.toml)
ruff check .

# Tests (offline, fixtures only)
PYTHONPATH=. python -m pytest tests/test_job_record.py tests/test_schemas.py tests/test_entity_resolver.py -v

# Demo fixtures against schema
PYTHONPATH=. python -m pytest tests/test_job_record.py::TestJobRecordFixtures -v
```

## CI

Every code push builds a dependency image (`Dockerfile.ci`, tagged `sha-<commit>` + `latest` on the default branch, see [ADR 0003](docs/adr/0003-ci-latest-tag-strategy.md)) and runs all jobs inside it:

1. **lint** — `ruff check .`
2. **unit** — offline unit tests (no network)
3. **contract** — JobRecord schema + entity resolver fixtures
4. **run** — validates all demo records against the schema (master only)

## Documentation

- [Architecture diagrams](docs/architecture.md)
- [Case study — one posting end to end](docs/case-study.md)
- [Étude de cas — résumé (FR)](docs/case-study.fr.md)
- [ADR 0001 — JobRecord v1 schema](docs/adr/0001-jobrecord-v1-schema.md)
- [ADR 0002 — Deterministic job_id](docs/adr/0002-deterministic-job-id.md)
- [ADR 0003 — CI image tag strategy](docs/adr/0003-ci-latest-tag-strategy.md)
- [ADR 0004 — Privacy boundary](docs/adr/0004-privacy-boundary.md)
- [ADR 0005 — Test strategy](docs/adr/0005-test-strategy.md)
- [Field source matrix](pipeline/output/FIELD_SOURCE_MATRIX.md)

## License

MIT — see [LICENSE](LICENSE).
