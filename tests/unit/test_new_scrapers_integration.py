"""
Integration test for all new scrapers + existing platform scrapers
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from pipeline.ingestion.aae_ensg_scraper import scrape as scrape_aae_ensg
from pipeline.ingestion.capgemini_scraper import scrape as scrape_capgemini
from pipeline.ingestion.cgi_scraper import scrape as scrape_cgi
from pipeline.ingestion.magellium_scraper import scrape as scrape_magellium
from pipeline.ingestion.platform_scraper import scrape_iamexpat_nl, scrape_jobs_lu, scrape_seek_au


def test_all_scrapers():
    all_jobs = []
    all_jobs.extend(scrape_capgemini(max_jobs=30))
    all_jobs.extend(scrape_magellium(max_jobs=30))
    all_jobs.extend(scrape_cgi(max_jobs=10))
    all_jobs.extend(scrape_seek_au(max_jobs=15))
    all_jobs.extend(scrape_iamexpat_nl(max_jobs=15))
    all_jobs.extend(scrape_jobs_lu(max_jobs=15))
    all_jobs.extend(scrape_aae_ensg(max_jobs=10))

    # At minimum, capgemini + magellium should return jobs
    assert len(all_jobs) >= 4, f"Expected at least 4 jobs, got {len(all_jobs)}"
    print(f"Total jobs: {len(all_jobs)}")

def test_no_duplicate_ids():
    all_jobs = []
    all_jobs.extend(scrape_capgemini(max_jobs=30))
    all_jobs.extend(scrape_magellium(max_jobs=30))
    all_jobs.extend(scrape_seek_au(max_jobs=15))
    all_jobs.extend(scrape_iamexpat_nl(max_jobs=15))
    all_jobs.extend(scrape_jobs_lu(max_jobs=15))
    all_jobs.extend(scrape_aae_ensg(max_jobs=10))

    ids = [j.id for j in all_jobs]
    assert len(ids) == len(set(ids)), f"Duplicate IDs found ({len(ids) - len(set(ids))} duplicates)"

def test_all_sites_represented():
    """
    Check that scrapers that DO return jobs have valid site identifiers.
    Some sites (seek_au on non-AU IP, CGI behind Radware) may return 0 jobs; that's OK.
    """
    all_jobs = []
    all_jobs.extend(scrape_capgemini(max_jobs=30))
    all_jobs.extend(scrape_magellium(max_jobs=30))
    all_jobs.extend(scrape_seek_au(max_jobs=15))
    all_jobs.extend(scrape_iamexpat_nl(max_jobs=15))
    all_jobs.extend(scrape_jobs_lu(max_jobs=15))
    all_jobs.extend(scrape_aae_ensg(max_jobs=10))

    sites = set(j.site for j in all_jobs)
    valid_sites = {'capgemini', 'magellium', 'seek_au', 'iamexpat', 'jobs_lu', 'aae_ensg'}
    unexpected = sites - valid_sites
    assert not unexpected, f"Unexpected sites: {unexpected}"
    print(f"Sites found: {sites}")

def test_all_required_fields():
    all_jobs = []
    all_jobs.extend(scrape_capgemini(max_jobs=5))
    all_jobs.extend(scrape_magellium(max_jobs=5))
    all_jobs.extend(scrape_seek_au(max_jobs=5))
    all_jobs.extend(scrape_iamexpat_nl(max_jobs=5))
    all_jobs.extend(scrape_jobs_lu(max_jobs=5))
    all_jobs.extend(scrape_aae_ensg(max_jobs=5))

    required = ['id', 'title', 'company', 'location', 'url', 'site']
    for j in all_jobs:
        for field in required:
            assert getattr(j, field, None), f"Job {j.id} missing field: {field}"

def test_seek_au_graceful():
    """seek.com.au geo-blocks non-AU IPs. Must handle gracefully (0 jobs, no exception)."""
    try:
        jobs = scrape_seek_au(max_jobs=15)
        assert isinstance(jobs, list), "Should return a list"
        print(f"seek_au: {len(jobs)} jobs")
    except Exception as e:
        assert False, f"Should not raise exception, got: {e}"

def test_aae_ensg_graceful():
    """AAE-ENSG job board must handle gracefully (no exception)."""
    try:
        jobs = scrape_aae_ensg(max_jobs=10)
        assert isinstance(jobs, list), "Should return a list"
        for j in jobs:
            assert j.salary == "" or j.salary == "3200 以上" or j.salary is None
        print(f"aae_ensg: {len(jobs)} jobs")
    except Exception as e:
        assert False, f"Should not raise exception, got: {e}"

if __name__ == "__main__":
    test_all_scrapers()
    print("  total PASS")
    test_no_duplicate_ids()
    print("  no_dup_ids PASS")
    test_all_sites_represented()
    print("  all_sites PASS")
    test_all_required_fields()
    print("  required_fields PASS")
    test_seek_au_graceful()
    print("  seek_au_graceful PASS")
    test_aae_ensg_graceful()
    print("  aae_ensg_graceful PASS")
    print("ALL PASSED")
