# JobRecord v1 — Field Source Matrix

This document maps each `JobRecord` field to its origin in the pipeline.

| JobRecord Field | Source / Derivation | Notes |
|-----------------|---------------------|-------|
| **schema_version** | Constant `1.0.0` | Embedded in code |
| **job_id** | `generate_job_id()` — deterministic | Priority: source+source_job_id → canonical_url → content hash |
| **source** | Scraper module name | One of `VALID_SOURCES` enum |
| **source_job_id** | Raw job data from source API/HTML | `job.id` from JobSpy; Greenhouse `id`; Lever `id`; SmartRecruiters `id`; Workday `jobId`; company site `jobId`; GeoRezo thread ID; `None` if unavailable |
| **canonical_url** | `job.url` → `clean_url()` | Tracking params stripped (utm_*, fbclid, gclid, etc.) |
| **title** | `job.title` → whitespace normalized | |
| **company** | `job.company` → `normalize_company_name()` | Fuzzy-matched against `KNOWN_COMPANIES` whitelist |
| **location** | `job.location` → `normalize_location()` | Fuzzy-matched against `KNOWN_LOCATIONS` whitelist |
| **employment_type** | `job.job_type` → `normalize_job_type()` | Maps variants to: CDI, CDD, Stage, Alternance, Apprentissage, Freelance, VIE, Part-time, Contract |
| **remote** | `job.remote` → `normalize_remote()` | Maps variants to: Yes, Partial, No |
| **salary** | `job.salary` (raw, stripped) | No normalization; preserved as-is from source |
| **description** | `job.description` → HTML stripped, whitespace normalized | |
| **published_at** | Source-provided date (if available) | ISO 8601 UTC; `None` if source doesn't provide |
| **discovered_at** | Pipeline run timestamp | ISO 8601 UTC; set at `_now_utc()` during record creation |
| **first_seen_at** | `existing_record.first_seen_at` or `discovered_at` | Preserved across runs for known jobs |
| **last_seen_at** | Pipeline run timestamp | Updated to current run time on each sighting |
| **content_hash** | SHA-256(title \| company \| location \| description) | For change detection; recomputed each run |
| **status** | Default `"active"`; can be updated to `closed`/`expired`/`filled` | Not yet automated; requires Phase 2 dedupe logic |
| **normalization_warnings** | Collected during cleaning | E.g., "fuzzy_company_match_below_threshold", "missing_job_type" |
| **analysis.hard_filter** | `hard_filter()` + `FranceGeoJobScreener` (if not global_mode) | `passed`, `reasons[]`, `missing_skills[]` |
| **analysis.screening** | `FranceGeoJobScreener.screen()` (if not global_mode) | Decision, 5-dim scores, skills, gap analysis, rules_version, model_version |
| **analysis.ranking** | `ThinkingKernel.evaluate()` | `final_score`, `thinking_trace`, `kernel_version` |

---

## Source-Specific Field Availability

| Source | source_job_id | published_at | employment_type | remote | salary |
|--------|---------------|--------------|-----------------|--------|--------|
| **JobSpy (LinkedIn/Indeed)** | `job.id` (internal) | Sometimes | Sometimes | Sometimes | Sometimes |
| **Greenhouse API** | `job.id` (string) | `job.updated_at` | Sometimes | Sometimes | Rarely |
| **Lever API** | `job.id` | `job.createdAt` | Sometimes | Sometimes | Rarely |
| **SmartRecruiters API** | `job.id` | `job.postedDate` | Sometimes | Sometimes | Sometimes |
| **Employer career site A** | HTML/JSON `id` | Sometimes | Often | Often | Rarely |
| **Employer career site B** | API `id` | Sometimes | Often | Often | Sometimes |
| **Employer career site C** | HTML `data-job-id` | Sometimes | Often | Often | Sometimes |
| **GeoRezo** | Thread ID from URL | Forum post date | Rarely | Rarely | Never |
| **Seek.au** | HTML `data-job-id` | Sometimes | Often | Often | Sometimes |
| **Jobat.be** | HTML `id` | Sometimes | Often | Often | Sometimes |
| **Oikotie.fi** | HTML `id` | Sometimes | Often | Often | Sometimes |
| **IamExpat.nl** | HTML `id` | Sometimes | Often | Often | Sometimes |
| **Jobs.lu** | HTML `id` | Sometimes | Often | Often | Sometimes |

> Employer-specific career-site adapters are maintained in the private pipeline; rows A/B/C describe the field patterns they follow. They are not published in this snapshot.

> **Note**: "Sometimes" means the field is present in the source response but not guaranteed. The pipeline handles missing fields gracefully (sets to `None` / empty string).

---

## Normalization Rules Summary

### Company Name (`normalize_company_name`)
1. Strip HTML tags & decode entities
2. Exact match in `KNOWN_COMPANIES` (case-insensitive)
3. Fuzzy match (rapidfuzz WRatio ≥ 82) against `KNOWN_COMPANIES`
4. Return original if no match

### Location (`normalize_location`)
1. Exact match in `KNOWN_LOCATIONS` (case-insensitive)
2. Fuzzy match (rapidfuzz WRatio ≥ 82) against `KNOWN_LOCATIONS`
3. Return cleaned original if no match

### Job Type (`normalize_job_type`)
Maps variants to canonical:
- CDI: `cdi`, `full-time`, `full time`, `permanent`, `indefinite`, `employee, full time`, `employee full-time`
- CDD: `cdd`, `contract`, `temporary`
- Stage: `stage`, `internship`, `intern`
- Alternance: `alternance`
- Apprentissage: `apprentissage`, `apprenticeship`
- Freelance: `freelance`, `consultant`, `indépendant`
- VIE: `vie`
- Part-time: `part-time`, `part time`
- Contract: `contract` (when not CDD)

### Remote (`normalize_remote`)
- Yes: `yes`, `remote`, `télétravail`, `full remote`, `fully remote`, `100% remote`, `remoto`
- Partial: `partial`, `partiel`, `hybrid`, `partially remote`, `occasionnel`
- No: `no`, `non`, `onsite`, `sur site`, `présentiel`

### URL Cleaning (`clean_url`)
Removes tracking parameters: `utm_*`, `fbclid`, `gclid`, `msclkid`, `dclid`, `mc_cid`, `mc_eid`, `_ga`, `_gl`, `ref*`, `source`, `src`, `via`, `igshid`

---

## Deterministic Job ID Algorithm

```
generate_job_id(source, source_job_id, canonical_url, title, company, location):
  1. If source_job_id exists:
       candidate = f"{source}.{sanitize(source_job_id)}"
       if valid(candidate): return candidate
  2. If canonical_url exists:
       url_base = netloc + path
       url_hash = sha256(url_base)[:16]
       candidate = f"{source}.url.{url_hash}"
       return candidate
  3. content = f"{title}|{company}|{location}".lower()
     content_hash = sha256(content)[:16]
     candidate = f"{source}.content.{content_hash}"
     return candidate
```

**Properties:**
- Same job → same `job_id` across runs (if source_job_id or URL stable)
- Different jobs → different `job_id` (collision resistance via SHA-256)
- Max 128 chars, lowercase, alphanumeric + `._-` only
- Source prefix enables partitioning by source

---

## Change Detection Strategy

On each pipeline run:
1. Fetch jobs from all sources
2. Convert each to `JobRecord` (computes `job_id`, `content_hash`)
3. Load existing records from local JSONL store (keyed by `job_id`)
4. For each new record:
   - If `job_id` not in store → **NEW** job
   - If `job_id` in store but `content_hash` differs → **UPDATED** job
   - If `job_id` in store and `content_hash` same → **UNCHANGED** job
5. Jobs absent from the current run are not retained in the current snapshot; automatic CLOSED/EXPIRED transitions are not implemented yet.
6. Write updated records back to store

This enables:
- Historical tracking of job postings
- Diffing description changes (salary updates, requirement changes)
- Reliable "new jobs today" filtering for Vault integration