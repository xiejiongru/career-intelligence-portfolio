"""
Test Magellium scraper
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from pipeline.ingestion.magellium_scraper import scrape


def test_magellium_basic():
    jobs = scrape(max_jobs=30)
    assert len(jobs) > 0, "Should return at least 1 job"
    print(f"Magellium: {len(jobs)} jobs")

def test_magellium_fields():
    jobs = scrape(max_jobs=30)
    for j in jobs:
        assert j.title, f"Job {j.id} missing title"
        assert j.company == "Magellium", f"Job {j.id} wrong company: {j.company}"
        assert j.url, f"Job {j.id} missing url"
        assert j.site == "magellium", f"Job {j.id} wrong site"
        assert j.id.startswith("magellium-"), f"Job {j.id} wrong id prefix"

def test_magellium_dedup():
    jobs = scrape(max_jobs=30)
    urls = [j.url for j in jobs]
    assert len(urls) == len(set(urls)), "Duplicate URLs found (dedup failed)"

def test_magellium_no_voir_offre():
    jobs = scrape(max_jobs=30)
    for j in jobs:
        assert "Voir" not in j.title, f"Filtered 'Voir l offre' text: {j.title}"

def test_magellium_url_format():
    jobs = scrape(max_jobs=30)
    for j in jobs:
        assert j.url.startswith("http"), f"Job {j.id} url should start with http"
        assert "offre_emploi" in j.url, f"Job {j.id} url missing offre_emploi"

if __name__ == "__main__":
    test_magellium_basic()
    print("  basic PASS")
    test_magellium_fields()
    print("  fields PASS")
    test_magellium_dedup()
    print("  dedup PASS")
    test_magellium_no_voir_offre()
    print("  no_voir_offre PASS")
    test_magellium_url_format()
    print("  url_format PASS")
    print("ALL PASSED")
