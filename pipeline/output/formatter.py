import csv
import json
import os
import shutil
from datetime import datetime, timedelta
from typing import List

from rich.console import Console
from rich.table import Table

from ..ingestion.models import JobPosting, validate_job_posting
from .schema import CSV_FIELDNAMES, job_to_csv_row, serialize_job

OUTPUT_BASE = "output"


def get_output_dir() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    dirpath = os.path.join(OUTPUT_BASE, today)
    os.makedirs(dirpath, exist_ok=True)
    return dirpath


def _write_latest(target_dir: str, ext: str):
    latest_path = os.path.join(OUTPUT_BASE, f"latest{ext}")
    source_path = os.path.join(target_dir, f"output{ext}")
    if os.path.exists(source_path):
        shutil.copy2(source_path, latest_path)


def cleanup_old_outputs(days: int = 7):
    cutoff = datetime.now() - timedelta(days=days)
    if not os.path.exists(OUTPUT_BASE):
        return
    for entry in os.listdir(OUTPUT_BASE):
        entry_path = os.path.join(OUTPUT_BASE, entry)
        if not os.path.isdir(entry_path):
            continue
        try:
            dir_date = datetime.strptime(entry, "%Y-%m-%d")
            if dir_date < cutoff:
                shutil.rmtree(entry_path)
                print(f"  cleaned {entry_path}")
        except ValueError:
            continue


def display_results(jobs: List[JobPosting]):
    console = Console()
    table = Table(title="Job Filtering Pipeline Results")

    table.add_column("Title", style="cyan", no_wrap=False)
    table.add_column("Company", style="magenta")
    table.add_column("Score", justify="right", style="green")
    table.add_column("Reason", style="white")

    for job in jobs:
        table.add_row(
            job.title,
            job.company,
            f"{job.final_score:.1f}",
            job.reason,
        )

    console.print(table)


def save_to_json(jobs: List[JobPosting], file_path: str):
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)

    seen_ids = set()
    existing = []
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                existing = json.load(f)
                seen_ids = {e.get("id") for e in existing if e.get("id")}
            except (json.JSONDecodeError, ValueError):
                existing = []

    new_count = 0
    for job in jobs:
        job_id = job.id or f"{job.site}-{job.title[:20]}"
        if job_id in seen_ids:
            continue
        errors = validate_job_posting(job)
        if errors:
            continue
        seen_ids.add(job_id)
        existing.append(serialize_job(job))
        new_count += 1

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    if new_count > 0:
        print(f"  wrote {len(existing)} jobs ({new_count} new, {len(existing) - new_count} existing) to {file_path}")


def save_to_csv(jobs: List[JobPosting], file_path: str):
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)

    seen_ids = set()
    existing_rows = []
    if os.path.exists(file_path):
        with open(file_path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                seen_ids.add(row.get("URL", ""))
                existing_rows.append(row)

    new_count = 0
    with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()

        for row in existing_rows:
            writer.writerow(row)

        for job in jobs:
            errors = validate_job_posting(job)
            if errors:
                continue

            url = job.url or ""
            if url in seen_ids:
                continue
            seen_ids.add(url)

            writer.writerow(job_to_csv_row(job))
            new_count += 1

    if new_count > 0:
        print(f"  wrote {len(seen_ids)} jobs ({new_count} new, {len(seen_ids) - new_count} existing) to {file_path}")


def save_with_history(jobs: List[JobPosting], ext: str = "json"):
    out_dir = get_output_dir()
    ext = ext.lstrip(".")
    filename = f"output.{ext}"
    filepath = os.path.join(out_dir, filename)
    if ext == "json":
        save_to_json(jobs, filepath)
    else:
        save_to_csv(jobs, filepath)
    _write_latest(out_dir, f".{ext}")
    cleanup_old_outputs()
    return filepath


def save_artifacts(jobs: List[JobPosting], base_dir: str = "artifacts"):
    today = datetime.now().strftime("%Y-%m-%d")
    date_dir = os.path.join(base_dir, today)

    batch_num = 1
    if os.path.exists(date_dir):
        batches = [d for d in os.listdir(date_dir) if d.startswith("batch_")]
        if batches:
            batch_nums = [int(b.split("_")[1]) for b in batches]
            batch_num = max(batch_nums) + 1

    batch_dir = os.path.join(date_dir, f"batch_{batch_num}")

    site_jobs = {}
    for job in jobs:
        site = getattr(job, "site", "unknown")
        if site not in site_jobs:
            site_jobs[site] = []
        site_jobs[site].append(job)

    for site, jobs_list in site_jobs.items():
        site_dir = os.path.join(batch_dir, site)
        os.makedirs(site_dir, exist_ok=True)
        save_to_json(jobs_list, os.path.join(site_dir, "output.json"))

    return batch_dir
