"""
Test CGI scraper (blocked by Radware - verify graceful handling)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from pipeline.ingestion.cgi_scraper import scrape


def test_cgi_graceful():
    jobs = scrape(max_jobs=10)
    assert isinstance(jobs, list), "Should return a list"
    assert len(jobs) == 0, "Should return 0 jobs (blocked by Radware)"
    print(f"CGI: {len(jobs)} jobs (correctly blocked)")

def test_cgi_no_exception():
    try:
        scrape(max_jobs=10)
        assert True, "Should not raise exception"
    except Exception as e:
        assert False, f"Should not raise exception, got: {e}"

if __name__ == "__main__":
    test_cgi_graceful()
    print("  graceful PASS")
    test_cgi_no_exception()
    print("  no_exception PASS")
    print("ALL PASSED")
