"""
Test Capgemini scraper
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from pipeline.ingestion.capgemini_scraper import scrape


def test_capgemini_basic():
    jobs = scrape(max_jobs=30)
    assert len(jobs) > 0, "Should return at least 1 job"
    print(f"Capgemini: {len(jobs)} jobs")

def test_capgemini_fields():
    jobs = scrape(max_jobs=30)
    for j in jobs:
        assert j.title, f"Job {j.id} missing title"
        assert j.company == "Capgemini" or j.company, f"Job {j.id} missing company"
        assert j.url, f"Job {j.id} missing url"
        assert j.site == "capgemini", f"Job {j.id} wrong site"
        assert j.id.startswith("capgemini-"), f"Job {j.id} wrong id prefix"

def test_capgemini_unique():
    jobs = scrape(max_jobs=30)
    ids = [j.id for j in jobs]
    assert len(ids) == len(set(ids)), "Duplicate job IDs found"
    titles = [j.title for j in jobs]
    assert len(titles) == len(set(titles)), "Duplicate job titles found"

def test_capgemini_url_format():
    jobs = scrape(max_jobs=30)
    for j in jobs:
        assert j.url.startswith("http"), f"Job {j.id} url should start with http"

def test_capgemini_max_jobs():
    jobs = scrape(max_jobs=10)
    assert len(jobs) <= 10, f"Should respect max_jobs limit (got {len(jobs)})"

if __name__ == "__main__":
    test_capgemini_basic()
    print("  basic PASS")
    test_capgemini_fields()
    print("  fields PASS")
    test_capgemini_unique()
    print("  unique PASS")
    test_capgemini_url_format()
    print("  url_format PASS")
    test_capgemini_max_jobs()
    print("  max_jobs PASS")
    print("ALL PASSED")
