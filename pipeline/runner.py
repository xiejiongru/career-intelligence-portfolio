import json
import logging
import os
import time
from datetime import datetime, timezone

from pipeline.filtering.hard_filter import hard_filter
from pipeline.ingestion.custom_scraper import scrape_custom_urls
from pipeline.ingestion.jobspy_scraper import scrape as scrape_jobs_jobspy
from pipeline.ingestion.models import JobPosting
from pipeline.matching.france_geo_screening import FranceGeoJobScreener
from pipeline.matching.geomatics_jd_parser import GeomaticsJDParser
from pipeline.matching.thinking_kernel import ThinkingKernel
from pipeline.output.formatter import (
    display_results,
    save_artifacts,
    save_with_history,
)
from pipeline.output.job_record import JobRecord, generate_job_id, job_record_to_jsonl
from pipeline.resume.schemas import load_resume, resume_to_text
from pipeline.resume.skill_extractor import extract_skills, get_all_skills_flat
from pipeline.utils.country_utils import is_allowed_country
from pipeline.utils.entity_resolver import clean_jobs
from pipeline.utils.structured_logging import (
    FailureCategory,
    PhaseMetrics,
    PipelineLogger,
    RunSummary,
    categorize_exception,
    setup_structured_logging,
)

# Setup structured logging (JSON in CI, human-readable locally)
is_ci = os.environ.get("GITHUB_ACTIONS") == "true"
setup_structured_logging(
    level=logging.INFO,
    json_output=is_ci,
    log_file="output/pipeline.log" if not is_ci else None,
)

log = PipelineLogger("pipeline.runner")


async def _scrape(config: dict) -> tuple[list[JobPosting], dict]:
    log.info("--- Phase 1: Scrape ---")
    jobs: list[JobPosting] = []
    source_stats: dict = {}

    t0 = time.monotonic()
    sites_to_scrape = config["search"].get("sites", [])
    if sites_to_scrape:
        log.info(f"Starting JobSpy for sites: {sites_to_scrape}")
        try:
            jobspy_jobs = scrape_jobs_jobspy(config["search"])
            source_stats["JobSpy"] = len(jobspy_jobs)
            jobs.extend(jobspy_jobs)
        except Exception as e:
            cat = categorize_exception(e)
            log.error(f"JobSpy scrape failed: {e}", failure_category=cat, source="jobspy")
            source_stats["JobSpy"] = 0

    log.info("Starting Custom Scraper (GeoRezo + ATS + platforms)...")
    try:
        custom_jobs = await scrape_custom_urls(config["search"], config["llm"])
        source_stats["Custom"] = len(custom_jobs)
        jobs.extend(custom_jobs)
    except Exception as e:
        cat = categorize_exception(e)
        log.error(f"Custom scrape failed: {e}", failure_category=cat, source="custom")
        source_stats["Custom"] = 0

    elapsed = round(time.monotonic() - t0, 1)
    log.info(f"Scraped {len(jobs)} jobs in {elapsed}s. Sources: {source_stats}")

    # Phase 1b: Entity Normalization
    log.info("--- Phase 1b: Entity Normalization ---")
    t0 = time.monotonic()
    try:
        jobs = clean_jobs(jobs)
    except Exception as e:
        cat = categorize_exception(e)
        log.error(f"Entity normalization failed: {e}", failure_category=cat)
        raise
    elapsed = round(time.monotonic() - t0, 1)
    log.info(f"Normalized {len(jobs)} jobs in {elapsed}s")

    return jobs, source_stats


def _filter_and_screen(
    jobs: list[JobPosting], config: dict, user_skills: set[str]
) -> list[JobPosting]:
    log.info("--- Phase 2: Filter & Screen ---")
    t0 = time.monotonic()

    global_mode = config["pipeline"].get("global_mode", False)
    allowed_countries = config["search"].get("allowed_countries", [])
    screener = FranceGeoJobScreener(user_skills) if not global_mode else None
    parser = GeomaticsJDParser()

    if global_mode:
        log.info("Global mode — accepting jobs from all locations")
    else:
        log.info("France mode — filtering for France-based positions")

    passed: list[JobPosting] = []
    filtered_count = 0
    country_filtered = 0
    hard_filtered = 0
    screening_filtered = 0

    for job in jobs:
        try:
            if allowed_countries and not is_allowed_country(job.location, allowed_countries):
                job.passed_hard_filter = False
                country_filtered += 1
                continue

            hard_filter(job, user_skills, config)

            if screener:
                job.screening_results = screener.screen(job)
                if job.screening_results["decision"] == "skip" or job.screening_results.get("filtered", False):
                    job.passed_hard_filter = False
                    screening_filtered += 1
            else:
                job.screening_results = {
                    "decision": "apply",
                    "score": 50,
                    "filtered": False,
                    "filter_reasons": [],
                    "match_scores": {},
                    "skills": {},
                    "gap_analysis": {},
                    "seniority": "",
                    "summary": "",
                }

            job.structured_data = parser.parse(job)

            if job.passed_hard_filter:
                passed.append(job)
            else:
                hard_filtered += 1
        except Exception as e:
            cat = categorize_exception(e)
            log.error(f"Filter/screen failed for job {job.id}: {e}", failure_category=cat, job_id=job.id)
            filtered_count += 1

    elapsed = round(time.monotonic() - t0, 1)
    log.info(
        f"{len(passed)}/{len(jobs)} passed hard filter in {elapsed}s "
        f"(country={country_filtered}, hard={hard_filtered}, screening={screening_filtered})"
    )
    return passed


def _rank(jobs: list[JobPosting], config: dict) -> list[JobPosting]:
    log.info("--- Phase 3: Rank ---")
    t0 = time.monotonic()

    ranking_cfg = config.get("ranking", {})
    kernel = ThinkingKernel()
    tk_context = {
        "target_skills": ranking_cfg.get("target_skills", []),
        "domain_keywords": ranking_cfg.get("domain_keywords", []),
        "preferred_technologies": ranking_cfg.get("preferred_technologies", []),
        "allowed_locations": ranking_cfg.get("location_bonus", []),
    }

    for job in jobs:
        try:
            result = kernel.evaluate(job, tk_context)
            job.final_score = result.final_score
            job.thinking_trace = result.trace
        except Exception as e:
            cat = categorize_exception(e)
            log.error(f"Ranking failed for job {job.id}: {e}", failure_category=cat, job_id=job.id)
            job.final_score = 0.0
            job.thinking_trace = f"Ranking error: {e}"

    results = sorted(jobs, key=lambda j: j.final_score, reverse=True)
    elapsed = round(time.monotonic() - t0, 1)
    log.info(f"Ranked {len(results)} jobs in {elapsed}s")
    return results


def _collect_metrics(
    jobs: list[JobPosting],
    config: dict,
    source_stats: dict,
    pipeline_duration: float,
) -> dict:
    scores = sorted(j.final_score for j in jobs)
    n = len(scores)

    percentiles = {}
    if n > 0:
        for p in [25, 50, 75, 90]:
            idx = int(p / 100 * n)
            percentiles[f"p{p}"] = round(scores[min(idx, n - 1)], 1)

    return {
        "run_id": datetime.now().isoformat(),
        "pipeline_duration_sec": pipeline_duration,
        "total_jobs": len(jobs),
        "passed_filter": sum(1 for j in jobs if j.passed_hard_filter),
        "failed_filter": sum(1 for j in jobs if not j.passed_hard_filter),
        "sources": source_stats,
        "score_distribution": percentiles,
        "config_snapshot": {
            "global_mode": config.get("pipeline", {}).get("global_mode", False),
            "top_n": config.get("pipeline", {}).get("top_n", 20),
            "target_skills_count": len(config.get("ranking", {}).get("target_skills", [])),
        },
    }


def _load_existing_records(jsonl_path: str) -> dict[str, JobRecord]:
    """Load existing JobRecords from JSONL file, keyed by job_id."""
    records = {}
    if not os.path.exists(jsonl_path):
        return records
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record_dict = json.loads(line)
                record = JobRecord(**record_dict)
                records[record.job_id] = record
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                log.warning(f"Skipping invalid record at line {line_num} in {jsonl_path}: {e}")
    return records


def _convert_to_job_records(
    jobs: list[JobPosting],
    config: dict,
    existing_records: dict[str, JobRecord],
) -> list[JobRecord]:
    """Convert JobPostings to JobRecords, preserving first_seen_at for known jobs."""
    records = []
    global_mode = config["pipeline"].get("global_mode", False)
    rules_version = "1.0"
    model_version = config.get("llm", {}).get("model", "unknown")
    kernel_version = "1.0"

    for job in jobs:
        try:
            source = getattr(job, "site", "unknown")
            job_id = getattr(job, "id", "")
            is_url_like = job_id.startswith("http") or job_id.startswith("www")
            source_job_id = job.id if job_id and not is_url_like else None

            published_at = job.date_posted if job.date_posted else None
            status = "active"

            # Determine screening results
            screening_results = getattr(job, "screening_results", None)
            if not global_mode and screening_results and screening_results.get("decision") == "skip":
                status = "closed"

            # Determine ranking result
            ranking_result = {
                "final_score": job.final_score,
                "thinking_trace": getattr(job, "thinking_trace", ""),
            }

            # Get hard filter info
            hard_filter_passed = job.passed_hard_filter
            hard_filter_reasons = getattr(job, "filter_reasons", [])
            missing_skills = job.missing_skills

            # Find existing record for first_seen_at preservation
            computed_job_id = generate_job_id(
                source=source,
                source_job_id=source_job_id,
                canonical_url=job.url,
                title=job.title,
                company=job.company,
                location=job.location,
            )
            existing = existing_records.get(computed_job_id)

            record = JobRecord.from_job_posting(
                job=job,
                source=source,
                source_job_id=source_job_id,
                published_at=published_at,
                status=status,
                hard_filter_passed=hard_filter_passed,
                hard_filter_reasons=hard_filter_reasons,
                missing_skills=missing_skills,
                screening_results=screening_results,
                ranking_result=ranking_result,
                rules_version=rules_version,
                model_version=model_version,
                kernel_version=kernel_version,
                existing_record=existing,
            )
            records.append(record)
        except Exception as e:
            cat = categorize_exception(e)
            log.error(f"JobRecord conversion failed for job {job.id}: {e}", failure_category=cat, job_id=job.id)

    return records


def _save_job_records(records: list[JobRecord], jsonl_path: str) -> tuple[int, int]:
    """Save JobRecords to JSONL file. Returns (new_count, updated_count)."""
    os.makedirs(os.path.dirname(jsonl_path), exist_ok=True)

    # Load existing to detect updates
    existing = _load_existing_records(jsonl_path)
    new_count = 0
    updated_count = 0

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for record in records:
            if record.job_id in existing:
                if existing[record.job_id].content_hash != record.content_hash:
                    updated_count += 1
                else:
                    # Unchanged, keep existing first_seen_at
                    pass
            else:
                new_count += 1
            f.write(job_record_to_jsonl(record) + "\n")

    return new_count, updated_count


def _export_for_vault(records: list[JobRecord], export_dir: str) -> int:
    """Export active, passed-filter jobs for Vault consumption."""
    os.makedirs(export_dir, exist_ok=True)
    count = 0
    for record in records:
        try:
            if record.status == "active" and record.analysis and record.analysis.hard_filter.passed:
                vault_file = os.path.join(export_dir, f"{record.job_id}.json")
                with open(vault_file, "w", encoding="utf-8") as f:
                    json.dump(record.to_dict(), f, ensure_ascii=False, indent=2)
                count += 1
        except Exception as e:
            cat = categorize_exception(e)
            log.error(f"Vault export failed for job {record.job_id}: {e}", failure_category=cat, job_id=record.job_id)
    return count


async def run_pipeline(config: dict) -> list[JobPosting]:
    """Single entry point: scrape → filter → screen → rank → save."""
    run_id = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    run_summary = RunSummary(run_id=run_id, started_at=run_id)
    pipeline_start = time.monotonic()

    log.info(f"Starting pipeline run {run_id}")

    # Phase 1: Scrape (+ normalization)
    phase1_start = time.monotonic()
    jobs, source_stats = await _scrape(config)
    phase1_ms = (time.monotonic() - phase1_start) * 1000
    run_summary.total_jobs_scraped = len(jobs)
    run_summary.add_phase(PhaseMetrics(
        phase="scrape",
        started_at=datetime.fromtimestamp(pipeline_start, timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        duration_ms=phase1_ms,
        input_count=0,
        output_count=len(jobs),
    ))
    if not jobs:
        log.warning("No jobs scraped. Exiting.")
        run_summary.status = "failed"
        run_summary.add_error("scrape", FailureCategory.VALIDATION, "NoJobsError", "No jobs scraped from any source")
        _save_run_summary(run_summary)
        return []

    # Resume + skills (needed for screening)
    resume_path = config["resume"]["path"]
    resume = load_resume(resume_path)
    resume_text = resume_to_text(resume)
    skills_dict = extract_skills(resume_text)
    user_skills = get_all_skills_flat(skills_dict)
    log.info(f"User skills: {user_skills}")

    # Phase 2: Filter & Screen
    phase2_start = time.monotonic()
    passed = _filter_and_screen(jobs, config, user_skills)
    phase2_ms = (time.monotonic() - phase2_start) * 1000
    run_summary.total_jobs_normalized = len(jobs)
    run_summary.total_jobs_filtered = len(passed)
    run_summary.add_phase(PhaseMetrics(
        phase="filter_screen",
        started_at=datetime.fromtimestamp(phase2_start - phase2_ms/1000, timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        duration_ms=phase2_ms,
        input_count=len(jobs),
        output_count=len(passed),
    ))

    # Phase 3: Rank
    phase3_start = time.monotonic()
    ranked = _rank(passed, config)
    phase3_ms = (time.monotonic() - phase3_start) * 1000
    run_summary.total_jobs_ranked = len(ranked)
    run_summary.add_phase(PhaseMetrics(
        phase="rank",
        started_at=datetime.fromtimestamp(phase3_start - phase3_ms/1000, timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        duration_ms=phase3_ms,
        input_count=len(passed),
        output_count=len(ranked),
    ))

    # Display top results
    top_n = config.get("pipeline", {}).get("top_n", 20)
    display_results(ranked[:top_n])

    # Phase 4: Convert to JobRecord v1 + JSONL storage
    phase4_start = time.monotonic()
    log.info("--- Phase 4: JobRecord Conversion & Storage ---")

    jsonl_path = "data/job_records.jsonl"
    existing_records = _load_existing_records(jsonl_path)
    job_records = _convert_to_job_records(ranked, config, existing_records)
    new_count, updated_count = _save_job_records(job_records, jsonl_path)

    # Export for Vault (active, passed-filter jobs)
    vault_export_dir = "data/for_vault"
    vault_count = _export_for_vault(job_records, vault_export_dir)

    phase4_ms = (time.monotonic() - phase4_start) * 1000
    run_summary.total_job_records = len(job_records)
    run_summary.new_records = new_count
    run_summary.updated_records = updated_count
    run_summary.vault_exports = vault_count
    run_summary.add_phase(PhaseMetrics(
        phase="jobrecord_storage",
        started_at=datetime.fromtimestamp(phase4_start - phase4_ms/1000, timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        duration_ms=phase4_ms,
        input_count=len(ranked),
        output_count=len(job_records),
    ))

    log.info(
        f"Converted {len(job_records)} JobRecords "
        f"({new_count} new, {updated_count} updated) "
        f"in {phase4_ms/1000:.1f}s"
    )
    log.info(f"Exported {vault_count} jobs for Vault → '{vault_export_dir}'")

    # Save outputs (legacy)
    artifact_dir = save_artifacts(ranked)
    save_with_history(ranked, "json")
    save_with_history(ranked, "csv")

    # Metrics
    pipeline_duration = round(time.monotonic() - pipeline_start, 1)
    metrics = _collect_metrics(ranked, config, source_stats, pipeline_duration)
    metrics_dir = "output/metrics"
    os.makedirs(metrics_dir, exist_ok=True)
    metrics_path = os.path.join(
        metrics_dir, f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    log.info(f"Metrics saved to {metrics_path}")

    # Save run summary
    completed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    run_summary.completed_at = completed_at
    run_summary.duration_ms = (time.monotonic() - pipeline_start) * 1000
    run_summary.status = "success" if not run_summary.errors else "partial"
    _save_run_summary(run_summary)

    log.info(f"Done. {len(ranked)} jobs in {pipeline_duration}s → '{artifact_dir}'")
    return ranked


def _save_run_summary(run_summary: RunSummary) -> None:
    """Save run summary to JSON and markdown."""
    os.makedirs("output/runs", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # JSON
    json_path = f"output/runs/run_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(run_summary.to_json())

    # Markdown
    md_path = f"output/runs/run_{timestamp}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(run_summary.to_markdown())

    log.info(f"Run summary saved to {json_path} and {md_path}")
