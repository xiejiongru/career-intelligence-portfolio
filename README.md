# Career Intelligence Portfolio

AI-native career intelligence pipeline — scrapes, filters, screens, and ranks job postings, then exports them as a versioned, validated **JobRecord v1** JSON contract.

Public snapshot of the pipeline: schema, sanitized demo data, architecture diagrams, ADRs, and CI. Private configuration, real run data, and candidate information are excluded by design (see [ADR 0004](docs/adr/0004-privacy-boundary.md)).

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

Every push builds a dependency image (`Dockerfile.ci`, tagged `sha-<commit>` + `latest` on the default branch, see [ADR 0003](docs/adr/0003-ci-latest-tag-strategy.md)) and runs all jobs inside it:

1. **lint** — `ruff check .`
2. **unit** — offline unit tests (no network)
3. **contract** — JobRecord schema + entity resolver fixtures
4. **scraper-health** — live scraper checks (non-blocking)
5. **run** — validates all demo records against the schema (master only)

## Documentation

- [Architecture diagrams](docs/architecture.md)
- [ADR 0001 — JobRecord v1 schema](docs/adr/0001-jobrecord-v1-schema.md)
- [ADR 0002 — Deterministic job_id](docs/adr/0002-deterministic-job-id.md)
- [ADR 0003 — CI image tag strategy](docs/adr/0003-ci-latest-tag-strategy.md)
- [ADR 0004 — Privacy boundary](docs/adr/0004-privacy-boundary.md)
- [ADR 0005 — Test strategy](docs/adr/0005-test-strategy.md)
- [Field source matrix](pipeline/output/FIELD_SOURCE_MATRIX.md)

## License

MIT — see [LICENSE](LICENSE).
