"""
Unit tests for JobRecord v1 schema, validation, and job_id generation.
"""
import json
import pytest

from pipeline.ingestion.models import JobPosting
from pipeline.output.job_record import (
    JobRecord,
    generate_job_id,
    validate_job_record,
    job_record_to_jsonl,
    SCHEMA_VERSION,
)


class TestGenerateJobId:
    """Tests for deterministic job_id generation."""

    def test_strategy1_source_job_id(self):
        """Priority 1: source + source_job_id when available."""
        job_id = generate_job_id(
            source="greenhouse",
            source_job_id="456789",
            canonical_url="https://example.com/job/456789",
            title="Data Engineer",
            company="Dataiku",
            location="Paris",
        )
        assert job_id == "greenhouse.456789"

    def test_strategy1_source_job_id_sanitized(self):
        """source_job_id with special chars gets sanitized."""
        job_id = generate_job_id(
            source="linkedin",
            source_job_id="3829104567!@#",
            canonical_url="https://linkedin.com/jobs/view/3829104567",
            title="GIS Developer",
            company="ESRI",
            location="Paris",
        )
        assert job_id == "linkedin.3829104567___"

    def test_strategy2_canonical_url(self):
        """Priority 2: canonical_url when no source_job_id."""
        job_id = generate_job_id(
            source="indeed",
            source_job_id=None,
            canonical_url="https://fr.indeed.com/viewjob?jk=abc123&utm_source=email",
            title="DevOps Engineer",
            company="Schneider",
            location="Grenoble",
        )
        assert job_id.startswith("indeed.url.")
        assert len(job_id) <= 128
        # Same URL should produce same ID
        job_id2 = generate_job_id(
            source="indeed",
            source_job_id=None,
            canonical_url="https://fr.indeed.com/viewjob?jk=abc123&utm_source=email",
            title="DevOps Engineer",
            company="Schneider",
            location="Grenoble",
        )
        assert job_id == job_id2

    def test_strategy3_content_hash(self):
        """Priority 3: content hash fallback."""
        job_id = generate_job_id(
            source="georezo",
            source_job_id=None,
            canonical_url="",
            title="Géomaticien",
            company="Communauté d'Agglomération",
            location="Lyon",
        )
        assert job_id.startswith("georezo.content.")
        assert len(job_id) <= 128

    def test_deterministic_across_runs(self):
        """Same inputs always produce same job_id."""
        for _ in range(10):
            job_id = generate_job_id(
                source="tomtom",
                source_job_id="job-12345",
                canonical_url="https://careers.tomtom.com/job/job-12345",
                title="Backend Engineer",
                company="TomTom",
                location="Amsterdam",
            )
            assert job_id == "tomtom.job-12345"

    def test_different_jobs_different_ids(self):
        """Different jobs get different IDs."""
        id1 = generate_job_id("greenhouse", "1", "https://a.com", "A", "A", "Paris")
        id2 = generate_job_id("greenhouse", "2", "https://b.com", "B", "B", "Lyon")
        id3 = generate_job_id("greenhouse", None, "", "C", "C", "Paris")
        assert len({id1, id2, id3}) == 3

    def test_job_id_format_valid(self):
        """Generated IDs match the required pattern."""
        job_id = generate_job_id(
            source="linkedin",
            source_job_id="3829104567",
            canonical_url="https://linkedin.com/jobs/view/3829104567",
            title="GIS Developer",
            company="ESRI France",
            location="Paris",
        )
        assert job_id.islower() or job_id[0].islower()
        assert all(c.isalnum() or c in "._-" for c in job_id)
        assert len(job_id) <= 128


class TestJobRecordCreation:
    """Tests for JobRecord.from_job_posting()."""

    def make_job_posting(self, **overrides) -> JobPosting:
        defaults = {
            "id": "raw-1",
            "title": "Data Engineer",
            "company": "dataiku",
            "location": "Paris 08",
            "description": "Python, PostGIS, AWS, Docker, Kubernetes",
            "url": "https://boards-api.greenhouse.io/v1/boards/dataiku/jobs/456789?utm_source=linkedin",
            "site": "greenhouse",
            "job_type": "cdi",
            "salary": "55k-70k EUR",
            "date_posted": "2026-10-01",
            "remote": "hybrid",
            "experience": "3+ years",
            "education": "Master",
        }
        defaults.update(overrides)
        return JobPosting(**defaults)

    def test_from_job_posting_minimal(self):
        """Create record with minimal required args."""
        job = self.make_job_posting()
        record = JobRecord.from_job_posting(
            job=job,
            source="greenhouse",
            source_job_id="456789",
        )
        assert record.schema_version == SCHEMA_VERSION
        assert record.job_id == "greenhouse.456789"
        assert record.source == "greenhouse"
        assert record.source_job_id == "456789"
        assert record.company == "Dataiku"  # normalized
        assert record.location == "Paris"  # normalized
        assert record.employment_type == "CDI"  # normalized
        assert record.remote == "Partial"  # normalized
        assert "utm_source" not in record.canonical_url
        assert record.status == "active"
        assert record.content_hash is not None
        assert len(record.content_hash) == 64

    def test_from_job_posting_with_all_analysis(self):
        """Create record with full analysis data."""
        job = self.make_job_posting()
        record = JobRecord.from_job_posting(
            job=job,
            source="greenhouse",
            source_job_id="456789",
            published_at="2026-10-01T10:00:00Z",
            hard_filter_passed=True,
            hard_filter_reasons=[],
            missing_skills=[],
            screening_results={
                "decision": "apply",
                "score": 85.5,
                "filtered": False,
                "filter_reasons": [],
                "seniority": "mid",
                "match_scores": {
                    "tech_match": 90,
                    "function_match": 80,
                    "domain_match": 85,
                    "experience_match": 88,
                    "growth_potential": 82,
                },
                "skills": {
                    "gis": ["postgis", "gdal"],
                    "data": ["python", "sql"],
                    "devops": ["aws", "docker", "kubernetes"],
                    "programming": ["python", "sql"],
                },
                "gap_analysis": {
                    "missing_skills": [],
                    "risk_factors": [],
                    "leverage_points": ["strong python"],
                },
                "summary": "Strong match",
            },
            ranking_result={"final_score": 88.2, "thinking_trace": "Good match"},
        )
        assert record.analysis is not None
        assert record.analysis.hard_filter.passed is True
        assert record.analysis.screening is not None
        assert record.analysis.screening.decision == "apply"
        assert record.analysis.screening.match_scores["tech_match"] == 90.0
        assert record.analysis.ranking is not None
        assert record.analysis.ranking.final_score == 88.2

    def test_from_job_posting_failed_hard_filter(self):
        """Record for job that failed hard filter."""
        job = self.make_job_posting(job_type="alternance")
        record = JobRecord.from_job_posting(
            job=job,
            source="indeed",
            source_job_id=None,
            hard_filter_passed=False,
            hard_filter_reasons=["job_type_not_allowed: Alternance not in allowed_job_types"],
            missing_skills=[],
            screening_results=None,
            ranking_result=None,
        )
        assert record.analysis.hard_filter.passed is False
        assert "job_type_not_allowed" in record.analysis.hard_filter.reasons[0]
        assert record.analysis.screening is None
        assert record.analysis.ranking is None

    def test_from_job_posting_global_mode_no_screening(self):
        """Record in global mode (no FranceGeoJobScreener)."""
        job = self.make_job_posting()
        record = JobRecord.from_job_posting(
            job=job,
            source="tomtom",
            source_job_id="job-12345",
            hard_filter_passed=True,
            hard_filter_reasons=[],
            missing_skills=[],
            screening_results=None,  # global mode = no screening
            ranking_result={"final_score": 72.0, "thinking_trace": "Good tech match"},
        )
        assert record.analysis.screening is None
        assert record.analysis.ranking is not None

    def test_existing_record_preserves_first_seen_at(self):
        """first_seen_at preserved when updating existing record."""
        job = self.make_job_posting()
        existing = JobRecord.from_job_posting(
            job=job,
            source="greenhouse",
            source_job_id="456789",
        )
        # Manually create updated record with later timestamps to test preservation logic
        # (from_job_posting uses _now_utc() which has second precision)
        updated = JobRecord.from_job_posting(
            job=job,
            source="greenhouse",
            source_job_id="456789",
            existing_record=existing,
        )
        assert updated.first_seen_at == existing.first_seen_at
        # last_seen_at and discovered_at should be >= (same second or later)
        assert updated.last_seen_at >= existing.last_seen_at
        assert updated.discovered_at >= existing.discovered_at

    def test_content_hash_changes_on_description_change(self):
        """content_hash differs when description changes."""
        job1 = self.make_job_posting(description="Original description")
        job2 = self.make_job_posting(description="Updated description with Airflow")
        record1 = JobRecord.from_job_posting(job=job1, source="greenhouse", source_job_id="456789")
        record2 = JobRecord.from_job_posting(job=job2, source="greenhouse", source_job_id="456789")
        assert record1.content_hash != record2.content_hash
        assert record1.job_id == record2.job_id  # job_id stable


class TestJobRecordValidation:
    """Tests for JobRecord validation (dataclass __post_init__)."""

    def test_valid_record_passes(self):
        """Valid record passes validation."""
        JobRecord(
            schema_version=SCHEMA_VERSION,
            job_id="greenhouse.456789",
            source="greenhouse",
            source_job_id="456789",
            canonical_url="https://example.com/job",
            title="Data Engineer",
            company="Dataiku",
            location="Paris",
            employment_type="CDI",
            remote="Partial",
            salary="55k-70k EUR",
            description="Job description",
            published_at="2026-10-01T10:00:00Z",
            discovered_at="2026-10-10T12:00:00Z",
            first_seen_at="2026-10-10T12:00:00Z",
            last_seen_at="2026-10-10T12:00:00Z",
            content_hash="a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
            status="active",
            normalization_warnings=[],
            analysis=None,
        )
        # No exception = valid

    def test_invalid_schema_version_fails(self):
        """Wrong schema_version raises ValueError."""
        with pytest.raises(ValueError, match="schema_version must be"):
            JobRecord(
                schema_version="2.0.0",
                job_id="greenhouse.456789",
                source="greenhouse",
                source_job_id="456789",
                canonical_url="https://example.com/job",
                title="Data Engineer",
                company="Dataiku",
                location="Paris",
                employment_type="CDI",
                remote="Partial",
                salary="55k-70k EUR",
                description="Job description",
                published_at="2026-10-01T10:00:00Z",
                discovered_at="2026-10-10T12:00:00Z",
                first_seen_at="2026-10-10T12:00:00Z",
                last_seen_at="2026-10-10T12:00:00Z",
                content_hash="a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
                status="active",
                normalization_warnings=[],
                analysis=None,
            )

    def test_invalid_job_id_fails(self):
        """Invalid job_id format raises ValueError."""
        with pytest.raises(ValueError, match="job_id must match"):
            JobRecord(
                schema_version=SCHEMA_VERSION,
                job_id="INVALID_ID!",  # uppercase and special char
                source="greenhouse",
                source_job_id="456789",
                canonical_url="https://example.com/job",
                title="Data Engineer",
                company="Dataiku",
                location="Paris",
                employment_type="CDI",
                remote="Partial",
                salary="55k-70k EUR",
                description="Job description",
                published_at="2026-10-01T10:00:00Z",
                discovered_at="2026-10-10T12:00:00Z",
                first_seen_at="2026-10-10T12:00:00Z",
                last_seen_at="2026-10-10T12:00:00Z",
                content_hash="a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
                status="active",
                normalization_warnings=[],
                analysis=None,
            )

    def test_invalid_source_fails(self):
        """Unknown source raises ValueError."""
        with pytest.raises(ValueError, match="source must be one of"):
            JobRecord(
                schema_version=SCHEMA_VERSION,
                job_id="unknown.123",
                source="unknown_source",
                source_job_id="123",
                canonical_url="https://example.com/job",
                title="Data Engineer",
                company="Dataiku",
                location="Paris",
                employment_type="CDI",
                remote="Partial",
                salary="55k-70k EUR",
                description="Job description",
                published_at="2026-10-01T10:00:00Z",
                discovered_at="2026-10-10T12:00:00Z",
                first_seen_at="2026-10-10T12:00:00Z",
                last_seen_at="2026-10-10T12:00:00Z",
                content_hash="a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
                status="active",
                normalization_warnings=[],
                analysis=None,
            )

    def test_invalid_employment_type_fails(self):
        """Invalid employment_type raises ValueError."""
        with pytest.raises(ValueError, match="employment_type must be one of"):
            JobRecord(
                schema_version=SCHEMA_VERSION,
                job_id="greenhouse.456789",
                source="greenhouse",
                source_job_id="456789",
                canonical_url="https://example.com/job",
                title="Data Engineer",
                company="Dataiku",
                location="Paris",
                employment_type="INVALID",
                remote="Partial",
                salary="55k-70k EUR",
                description="Job description",
                published_at="2026-10-01T10:00:00Z",
                discovered_at="2026-10-10T12:00:00Z",
                first_seen_at="2026-10-10T12:00:00Z",
                last_seen_at="2026-10-10T12:00:00Z",
                content_hash="a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
                status="active",
                normalization_warnings=[],
                analysis=None,
            )

    def test_invalid_remote_fails(self):
        """Invalid remote raises ValueError."""
        with pytest.raises(ValueError, match="remote must be one of"):
            JobRecord(
                schema_version=SCHEMA_VERSION,
                job_id="greenhouse.456789",
                source="greenhouse",
                source_job_id="456789",
                canonical_url="https://example.com/job",
                title="Data Engineer",
                company="Dataiku",
                location="Paris",
                employment_type="CDI",
                remote="INVALID",
                salary="55k-70k EUR",
                description="Job description",
                published_at="2026-10-01T10:00:00Z",
                discovered_at="2026-10-10T12:00:00Z",
                first_seen_at="2026-10-10T12:00:00Z",
                last_seen_at="2026-10-10T12:00:00Z",
                content_hash="a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
                status="active",
                normalization_warnings=[],
                analysis=None,
            )

    def test_invalid_status_fails(self):
        """Invalid status raises ValueError."""
        with pytest.raises(ValueError, match="status must be one of"):
            JobRecord(
                schema_version=SCHEMA_VERSION,
                job_id="greenhouse.456789",
                source="greenhouse",
                source_job_id="456789",
                canonical_url="https://example.com/job",
                title="Data Engineer",
                company="Dataiku",
                location="Paris",
                employment_type="CDI",
                remote="Partial",
                salary="55k-70k EUR",
                description="Job description",
                published_at="2026-10-01T10:00:00Z",
                discovered_at="2026-10-10T12:00:00Z",
                first_seen_at="2026-10-10T12:00:00Z",
                last_seen_at="2026-10-10T12:00:00Z",
                content_hash="a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
                status="INVALID",
                normalization_warnings=[],
                analysis=None,
            )

    def test_invalid_iso8601_fails(self):
        """Invalid ISO 8601 timestamp raises ValueError."""
        with pytest.raises(ValueError, match="discovered_at must be ISO 8601"):
            JobRecord(
                schema_version=SCHEMA_VERSION,
                job_id="greenhouse.456789",
                source="greenhouse",
                source_job_id="456789",
                canonical_url="https://example.com/job",
                title="Data Engineer",
                company="Dataiku",
                location="Paris",
                employment_type="CDI",
                remote="Partial",
                salary="55k-70k EUR",
                description="Job description",
                published_at="2026-10-01T10:00:00Z",
                discovered_at="not-a-timestamp",
                first_seen_at="2026-10-10T12:00:00Z",
                last_seen_at="2026-10-10T12:00:00Z",
                content_hash="a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
                status="active",
                normalization_warnings=[],
                analysis=None,
            )

    def test_invalid_content_hash_fails(self):
        """Invalid SHA-256 hash raises ValueError."""
        with pytest.raises(ValueError, match="content_hash must be 64-char"):
            JobRecord(
                schema_version=SCHEMA_VERSION,
                job_id="greenhouse.456789",
                source="greenhouse",
                source_job_id="456789",
                canonical_url="https://example.com/job",
                title="Data Engineer",
                company="Dataiku",
                location="Paris",
                employment_type="CDI",
                remote="Partial",
                salary="55k-70k EUR",
                description="Job description",
                published_at="2026-10-01T10:00:00Z",
                discovered_at="2026-10-10T12:00:00Z",
                first_seen_at="2026-10-10T12:00:00Z",
                last_seen_at="2026-10-10T12:00:00Z",
                content_hash="not-a-hash",
                status="active",
                normalization_warnings=[],
                analysis=None,
            )


class TestJobRecordSerialization:
    """Tests for JobRecord serialization."""

    def test_to_dict_roundtrip(self):
        """to_dict() produces dict that can recreate record."""
        job = JobPosting(
            id="raw-1", title="Data Engineer", company="dataiku", location="Paris",
            description="desc", url="https://example.com/job", site="greenhouse",
            job_type="cdi", remote="hybrid",
        )
        record = JobRecord.from_job_posting(job=job, source="greenhouse", source_job_id="456789")
        record_dict = record.to_dict()
        # Reconstruct
        record2 = JobRecord(**record_dict)
        assert record2.job_id == record.job_id
        assert record2.title == record.title
        assert record2.content_hash == record.content_hash

    def test_to_json_valid(self):
        """to_json() produces valid JSON."""
        job = JobPosting(
            id="raw-1", title="Data Engineer", company="dataiku", location="Paris",
            description="desc", url="https://example.com/job", site="greenhouse",
        )
        record = JobRecord.from_job_posting(job=job, source="greenhouse", source_job_id="456789")
        json_str = record.to_json()
        parsed = json.loads(json_str)
        assert parsed["job_id"] == record.job_id
        assert parsed["schema_version"] == SCHEMA_VERSION

    def test_job_record_to_jsonl(self):
        """job_record_to_jsonl produces single-line JSON."""
        job = JobPosting(
            id="raw-1", title="Data Engineer", company="dataiku", location="Paris",
            description="desc", url="https://example.com/job", site="greenhouse",
        )
        record = JobRecord.from_job_posting(job=job, source="greenhouse", source_job_id="456789")
        jsonl = job_record_to_jsonl(record)
        assert "\n" not in jsonl.strip()
        parsed = json.loads(jsonl)
        assert parsed["job_id"] == record.job_id


class TestValidateJobRecord:
    """Tests for JSON Schema validation."""

    def test_valid_fixture_passes(self):
        """Greenhouse fixture passes schema validation."""
        with open("tests/fixtures/job_records/job_record_v1_greenhouse.json") as f:
            record = json.load(f)
        errors = validate_job_record(record)
        assert errors == [], f"Validation errors: {errors}"

    def test_linkedin_fixture_passes(self):
        """LinkedIn fixture passes schema validation."""
        with open("tests/fixtures/job_records/job_record_v1_linkedin.json") as f:
            record = json.load(f)
        errors = validate_job_record(record)
        assert errors == [], f"Validation errors: {errors}"

    def test_failed_filter_fixture_passes(self):
        """Failed filter fixture passes schema validation."""
        with open("tests/fixtures/job_records/job_record_v1_indeed_failed_filter.json") as f:
            record = json.load(f)
        errors = validate_job_record(record)
        assert errors == [], f"Validation errors: {errors}"

    def test_global_mode_fixture_passes(self):
        """Global mode fixture passes schema validation."""
        with open("tests/fixtures/job_records/job_record_v1_tomtom_global.json") as f:
            record = json.load(f)
        errors = validate_job_record(record)
        assert errors == [], f"Validation errors: {errors}"

    def test_georezo_fixture_passes(self):
        """GeoRezo fixture passes schema validation."""
        with open("tests/fixtures/job_records/job_record_v1_georezo.json") as f:
            record = json.load(f)
        errors = validate_job_record(record)
        assert errors == [], f"Validation errors: {errors}"


class TestJobRecordFixtures:
    """Tests that verify fixture content matches expectations."""

    def test_greenhouse_fixture_has_correct_job_id(self):
        """Greenhouse fixture uses source_job_id strategy."""
        with open("tests/fixtures/job_records/job_record_v1_greenhouse.json") as f:
            record = json.load(f)
        assert record["job_id"] == "greenhouse.456789"
        assert record["source_job_id"] == "456789"

    def test_indeed_fixture_uses_url_strategy(self):
        """Indeed fixture (no source_job_id) uses URL strategy."""
        with open("tests/fixtures/job_records/job_record_v1_indeed_failed_filter.json") as f:
            record = json.load(f)
        assert record["source_job_id"] is None
        assert record["job_id"].startswith("indeed.url.")

    def test_tomtom_fixture_has_no_screening(self):
        """Global mode fixture has no screening analysis."""
        with open("tests/fixtures/job_records/job_record_v1_tomtom_global.json") as f:
            record = json.load(f)
        assert record["analysis"]["screening"] is None
        assert record["analysis"]["ranking"] is not None

    def test_updated_job_same_job_id_different_hash(self):
        """Updated job has same job_id but different content_hash."""
        with open("tests/fixtures/job_records/job_record_v1_greenhouse.json") as f:
            original = json.load(f)
        with open("tests/fixtures/job_records/job_record_v1_greenhouse_updated.json") as f:
            updated = json.load(f)
        assert original["job_id"] == updated["job_id"]
        assert original["content_hash"] != updated["content_hash"]
        assert updated["last_seen_at"] > original["last_seen_at"]
        assert updated["first_seen_at"] == original["first_seen_at"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])