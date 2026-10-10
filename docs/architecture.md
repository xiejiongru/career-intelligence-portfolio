# Architecture Diagrams

This document contains Mermaid diagrams describing the Career Intelligence Pipeline architecture.

---

## 1. End-to-End Data Flow

```mermaid
flowchart TD
    subgraph Sources ["📥 Job Sources"]
        JobSpy["JobSpy (LinkedIn, Indeed)"]
        ATS["ATS APIs (Greenhouse, Lever, SmartRecruiters)"]
        Custom["Custom Scrapers (GeoRezo, Company Sites)"]
        Platforms["Platform Scrapers (Seek, Jobat, Oikotie, etc.)"]
    end

    subgraph Ingestion ["🔄 Phase 1: Ingestion"]
        Scrape["scrape_jobs_jobspy()\nscrape_custom_urls()"]
        Normalize["clean_jobs()\nEntity Resolution\n• Company\n• Location\n• Job Type\n• Remote\n• URL cleaning"]
    end

    subgraph Filtering ["🔍 Phase 2: Filter & Screen"]
        Country["Country Whitelist"]
        HardFilter["hard_filter()\n• Contract Type\n• Mandatory Keywords\n• Known Technologies"]
        Screening["FranceGeoJobScreener\n• 5-dim scoring\n• Tech/Function/Domain\n• Experience/Growth\n• Decision: apply/maybe/skip"]
        Parser["GeomaticsJDParser\nStructured JD extraction"]
    end

    subgraph Ranking ["🏆 Phase 3: Rank"]
        Kernel["ThinkingKernel\n• System Layer (skills)\n• Human Layer (domain/location)\n• Critique Layer (buzzword check)"]
    end

    subgraph Output ["📦 Phase 4: JobRecord v1 + Storage"]
        Convert["JobRecord.from_job_posting()\n• Deterministic job_id\n• Content hash\n• ISO 8601 timestamps\n• Analysis metadata"]
        JSONL["data/job_records.jsonl\n• Append-only\n• Dedupe by job_id\n• Preserve first_seen_at\n• Detect updates via content_hash"]
        Vault["data/for_vault/\n• Active + passed-filter\n• Per-job JSON files\n• Markdown Job Card ready"]
        Legacy["output/YYYY-MM-DD/\n• output.json / output.csv\n• artifacts/ per source"]
    end

    subgraph CI_CD ["🚀 CI/CD"]
        Build["Build Docker Image\n(sha-<commit> + latest on main)"]
        Lint["ruff lint"]
        Unit["Unit Tests (offline)"]
        Contract["Contract Tests\nJobRecord Schema\nEntity Resolver"]
        Health["Scraper Health Checks\n(non-blocking)"]
        Cron["Cron: every 2 days\nPulls :latest from main"]
    end

    JobSpy --> Scrape
    ATS --> Scrape
    Custom --> Scrape
    Platforms --> Scrape

    Scrape --> Normalize
    Normalize --> Country
    Country --> HardFilter
    HardFilter --> Screening
    HardFilter --> Parser
    Screening --> Kernel
    Parser --> Kernel

    Kernel --> Convert
    Convert --> JSONL
    Convert --> Vault
    Convert --> Legacy

    Build --> Lint
    Build --> Unit
    Build --> Contract
    Build --> Health
    Unit --> Cron
    Contract --> Cron
    Health -.-> Cron

    style JSONL fill:#e8f5e9,stroke:#2e7d32
    style Vault fill:#e3f2fd,stroke:#1565c0
    style Legacy fill:#fff3e0,stroke:#ef6c00
```

---

## 2. JobRecord v1 Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Discovered: Scraped from source
    Discovered --> Normalized: clean_jobs()
    Normalized --> Filtered: hard_filter() + country whitelist
    Filtered --> Screened: FranceGeoJobScreener (France mode)
    Filtered --> Ranked: ThinkingKernel (Global mode)
    Screened --> Ranked: ThinkingKernel
    Ranked --> JobRecord: JobRecord.from_job_posting()

    JobRecord --> JSONL_New: job_id not in JSONL
    JobRecord --> JSONL_Updated: job_id exists, content_hash changed
    JobRecord --> JSONL_Unchanged: job_id exists, content_hash same
    JobRecord --> Vault_Export: status=active AND hard_filter.passed=true

    JSONL_New --> [*]
    JSONL_Updated --> [*]
    JSONL_Unchanged --> [*]
    Vault_Export --> [*]

    note right of JobRecord
        Fields set:
        - job_id (deterministic)
        - content_hash (SHA-256)
        - discovered_at, first_seen_at, last_seen_at
        - analysis: hard_filter, screening, ranking
    end note

    note right of JSONL_Updated
        Update detection:
        - Same job_id, different content_hash
        - Preserves original first_seen_at
        - Updates last_seen_at, discovered_at
    end note

    note right of JSONL_Unchanged
        No changes:
        - Keeps existing first_seen_at
        - Updates last_seen_at
    end note
```

---

## 3. Deterministic Job ID Generation

```mermaid
flowchart TD
    Start(["Generate Job ID"]) --> HasSourceID{"source_job_id\navailable?"}
    HasSourceID -->|Yes| Strategy1["Strategy 1:\nsource.source_job_id\n(e.g., greenhouse.456789)"]
    HasSourceID -->|No| HasURL{"canonical_url\navailable?"}
    HasURL -->|Yes| Strategy2["Strategy 2:\nsource.url.<url_sha256_16>\n(e.g., indeed.url.21548823e2eea3cb)"]
    HasURL -->|No| Strategy3["Strategy 3:\nsource.content.<content_sha256_16>\n(e.g., georezo.content.xxx)"]

    Strategy1 --> Validate["Validate format:\n^[a-z0-9][a-z0-9._-]{0,127}$"]
    Strategy2 --> Validate
    Strategy3 --> Validate

    Validate -->|Valid| Return["Return job_id"]
    Validate -->|Invalid| Fallback["Fallback: source.fallback.<hash>"]

    Return --> Done(["Done"])
    Fallback --> Done
```

---

## 4. CI/CD Pipeline

```mermaid
flowchart LR
    subgraph Trigger ["Trigger"]
        PushMain["push to main"]
        PR["pull_request to main"]
        Dispatch["workflow_dispatch"]
    end

    subgraph Build ["Build Job"]
        BuildDocker["docker/build-push-action\n• Dockerfile.ci\n• Cache: type=gha\n• Tags: sha-<commit>, latest (main only)"]
    end

    subgraph Parallel ["Parallel Jobs (needs: build)"]
        Lint["ruff check"]
        Unit["pytest unit/contract\n(offline, fixtures only)"]
        Contract["pytest contract\nJobRecord Schema\nEntity Resolver"]
        Health["pytest scraper health\n(continue-on-error: true)"]
    end

    subgraph Deploy ["Deploy (main only)"]
        Run["run_pipeline.py\n• Full pipeline\n• Upload artifacts"]
    end

    PushMain --> BuildDocker
    PR --> BuildDocker
    Dispatch --> BuildDocker

    BuildDocker --> Lint
    BuildDocker --> Unit
    BuildDocker --> Contract
    BuildDocker --> Health

    Lint --> Run
    Unit --> Run
    Contract --> Run
    Health -.-> Run

    style BuildDocker fill:#e8eaf6,stroke:#3f51b5
    style Run fill:#e8f5e9,stroke:#2e7d32
    style Health fill:#fff3e0,stroke:#ef6c00
```

---

## 5. Cron Scraper (Decoupled from CI)

```mermaid
sequenceDiagram
    participant Cron as "GitHub Actions Cron\n(every 2 days, 06:00 UTC)"
    participant GHCR as "ghcr.io/org/repo:latest"
    participant Runner as "Ubuntu Runner\n(container: latest)"
    participant Repo as "Repository"
    participant Artifacts as "GitHub Artifacts\n(retention: 30 days)"

    Cron->>GHCR: Pull :latest image\n(only pushed by CI on main)
    Cron->>Runner: Start container
    Runner->>Repo: Checkout code
    Runner->>Runner: mkdir -p output
    Runner->>Runner: PYTHONPATH=. python run_pipeline.py
    Runner->>Runner: Scrape → Normalize → Filter → Rank → JobRecord
    Runner->>Artifacts: Upload output/latest.csv, output/latest.json, output/**
    Runner-->>Cron: Complete
    alt Failure
        Runner->>GitHub: Create issue "Scraper Cron failed on DATE"
    end
```

---

## 6. Data Model Relationships

```mermaid
erDiagram
    JOB_POSTING ||--o{ JOB_RECORD : "converted to"
    JOB_POSTING {
        string id
        string title
        string company
        string location
        string description
        string url
        string site
        string job_type
        string salary
        string date_posted
        string remote
        float final_score
        string thinking_trace
        json screening_results
        json structured_data
    }
    JOB_RECORD {
        string schema_version PK
        string job_id PK
        string source
        string source_job_id FK
        string canonical_url
        string title
        string company
        string location
        string employment_type
        string remote
        string salary
        string description
        datetime published_at
        datetime discovered_at
        datetime first_seen_at
        datetime last_seen_at
        string content_hash
        string status
        json normalization_warnings
        json analysis
    }
    ANALYSIS {
        json hard_filter
        json screening
        json ranking
    }
    HARD_FILTER {
        boolean passed
        string[] reasons
        string[] missing_skills
    }
    SCREENING {
        string decision
        float score
        boolean filtered
        string[] filter_reasons
        string seniority
        json match_scores
        json skills
        json gap_analysis
        string summary
        string rules_version
        string model_version
    }
    RANKING {
        float final_score
        string thinking_trace
        string kernel_version
    }
    JOB_RECORD ||--|| ANALYSIS : contains
    ANALYSIS ||--|| HARD_FILTER : includes
    ANALYSIS ||--o{ SCREENING : includes
    ANALYSIS ||--o{ RANKING : includes
```

---

## 7. Vault Integration Flow

```mermaid
flowchart LR
    subgraph Pipeline ["Job Pipeline (Private)"]
        JSONL["data/job_records.jsonl\n(append-only, deduped)"]
        VaultExport["data/for_vault/\n{job_id}.json"]
    end

    subgraph Vault ["Career Second Brain / prof-vault (Private)"]
        Import["Manual Import\nor Scripted Sync"]
        JobCard["Markdown Job Card\nper position"]
        Evidence["Experience Evidence\nInterview Notes\nContact Logs"]
        Decision["Human Decision\nApply / Pass / Follow-up"]
    end

    subgraph Portfolio ["Public Portfolio (GitHub)"]
        Schema["schemas/job-record-v1.json"]
        DemoData["data/demo/job_records_demo.jsonl"]
        Docs["docs/architecture.md\ndocs/adr/*.md"]
        Code["pipeline/ (sanitized)"]
    end

    JSONL --> VaultExport
    VaultExport --> Import
    Import --> JobCard
    JobCard --> Evidence
    JobCard --> Decision

    Schema -.-> Portfolio
    DemoData -.-> Portfolio
    Docs -.-> Portfolio
    Code -.-> Portfolio

    style Pipeline fill:#fce4ec,stroke:#c2185b
    style Vault fill:#e8eaf6,stroke:#3f51b5
    style Portfolio fill:#e8f5e9,stroke:#2e7d32
```