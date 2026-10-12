"""
Unit tests for the Entity Resolver (Data Cleaning Layer)
=========================================================
Covers:
- Company name normalization
- Location normalization
- Job type / remote / URL cleaning
- Full job cleaning
"""
import pytest

from pipeline.ingestion.models import JobPosting
from pipeline.utils.entity_resolver import (
    clean_job,
    clean_jobs,
    clean_url,
    normalize_company_name,
    normalize_job_type,
    normalize_location,
    normalize_remote,
)


class TestNormalizeCompanyName:
    def test_exact_match(self):
        assert normalize_company_name("edf") == "EDF"
        assert normalize_company_name("EDf") == "EDF"
        assert normalize_company_name("Total energies") == "TotalEnergies"

    def test_prefix_match(self):
        assert normalize_company_name("EDF France") == "EDF"
        assert normalize_company_name("Schneider Electric SE") == "Schneider Electric"

    def test_unknown_company_unchanged(self):
        assert normalize_company_name("Acme Corp") == "Acme Corp"

    def test_empty(self):
        assert normalize_company_name("") == "Unknown"
        assert normalize_company_name(None) == "Unknown"

    def test_esri_variants(self):
        assert normalize_company_name("esri") == "ESRI"
        assert normalize_company_name("esri france") == "ESRI France"


class TestNormalizeLocation:
    def test_paris_arrondissements(self):
        assert normalize_location("Paris 08") == "Paris"
        assert normalize_location("paris 11") == "Paris"
        assert normalize_location("Paris 20") == "Paris"

    def test_idf_variants(self):
        assert normalize_location("idf") == "Île-de-France"
        assert normalize_location("Île-de-France") == "Île-de-France"
        assert normalize_location("la défense") == "La Défense"

    def test_city_normalization(self):
        assert normalize_location("lyon") == "Lyon"
        assert normalize_location("marseille") == "Marseille"
        assert normalize_location("la defense") == "La Défense"

    def test_unknown_unchanged(self):
        assert normalize_location("Toulouse") == "Toulouse"


class TestNormalizeJobType:
    def test_cdi_variants(self):
        assert normalize_job_type("CDI") == "CDI"
        assert normalize_job_type("cdi") == "CDI"
        assert normalize_job_type("Full-Time") == "CDI"
        assert normalize_job_type("permanent") == "CDI"

    def test_cdd_variants(self):
        assert normalize_job_type("cdd") == "CDD"
        assert normalize_job_type("CDD") == "CDD"
        assert normalize_job_type("contract") == "CDD"

    def test_stage_variants(self):
        assert normalize_job_type("Stage") == "Stage"
        assert normalize_job_type("internship") == "Stage"

    def test_alternance(self):
        assert normalize_job_type("alternance") == "Alternance"
        assert normalize_job_type("Alternance") == "Alternance"

    def test_apprentissage(self):
        assert normalize_job_type("apprentissage") == "Apprentissage"
        assert normalize_job_type("apprenticeship") == "Apprentissage"

    def test_none(self):
        assert normalize_job_type(None) is None


class TestNormalizeRemote:
    def test_yes(self):
        assert normalize_remote("Yes") == "Yes"
        assert normalize_remote("remote") == "Yes"
        assert normalize_remote("télétravail") == "Yes"
        assert normalize_remote("FULL REMOTE") == "Yes"

    def test_partial(self):
        assert normalize_remote("Partial") == "Partial"
        assert normalize_remote("hybrid") == "Partial"
        assert normalize_remote("Partiel") == "Partial"

    def test_no(self):
        assert normalize_remote("No") == "No"
        assert normalize_remote("sur site") == "No"
        assert normalize_remote("onsite") == "No"

    def test_none(self):
        assert normalize_remote(None) is None


class TestCleanUrl:
    def test_tracking_params_removed(self):
        url = "https://example.com/job?id=123&utm_source=linkedin&fbclid=abc&gclid=xyz"
        cleaned = clean_url(url)
        assert "fbclid" not in cleaned
        assert "gclid" not in cleaned
        assert "utm_source" not in cleaned
        assert "id=123" in cleaned

    def test_utm_all_removed(self):
        url = "https://careers.company.com/job/456?utm_source=indeed&ref=email"
        cleaned = clean_url(url)
        assert "ref=" not in cleaned

    def test_clean_url_unchanged(self):
        url = "https://example.com/job?id=789"
        assert clean_url(url) == url

    def test_invalid_url(self):
        assert clean_url("not a url") == "not a url"


class TestCleanJob:
    def test_full_clean(self):
        raw = JobPosting(
            id="raw-1",
            title="  Data Engineer  ",
            company="edf",
            location="Paris 05",
            description="desc",
            url="https://x.com/job?fbclid=xxx",
            site="test",
            job_type="cdi",
            remote="remote",
        )
        cleaned = clean_job(raw)

        assert cleaned.title == "Data Engineer"
        assert cleaned.company == "EDF"
        assert cleaned.location == "Paris"
        assert cleaned.job_type == "CDI"
        assert cleaned.remote == "Yes"
        assert "fbclid" not in cleaned.url


class TestCleanJobs:
    def test_batch_clean(self):
        jobs = [
            JobPosting(id="1", title="A", company="schneider-electric", location="Paris 01",
                       description="x", url="https://x.com/1?fbclid=a", site="s", job_type="cdd"),
            JobPosting(id="2", title="B", company="EDF France", location="Lyon",
                       description="y", url="https://x.com/2", site="s", job_type="stage"),
        ]
        cleaned = clean_jobs(jobs)
        assert cleaned[0].company == "Schneider Electric"
        assert cleaned[0].location == "Paris"
        assert cleaned[1].company == "EDF"
        assert cleaned[1].location == "Lyon"
        assert cleaned[1].job_type == "Stage"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
