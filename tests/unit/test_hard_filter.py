import pytest

from pipeline.filtering.hard_filter import hard_filter
from pipeline.ingestion.models import JobPosting


@pytest.fixture
def config():
    return {
        "hard_filter": {
            "mandatory_keywords": ["required", "must have", "mandatory"],
            "known_technologies": {
                "languages": ["java", "python", "node", "go"],
                "frameworks": ["spring", "react", "django"],
                "databases": ["postgresql", "mongodb"],
                "tools": ["docker", "kubernetes", "git"],
            }
        }
    }

def test_filters_missing_mandatory_language(config):
    # JD requires Java, user only has python/docker -> should be filtered
    job = JobPosting(
        id="1", title="Dev", company="A", location="B", url="C", site="D",
        description="We required Java experience."
    )
    user_skills = {"python", "docker"}

    result = hard_filter(job, user_skills, config)
    assert result.passed_hard_filter is False
    assert "java" in result.missing_skills

def test_passes_matching_mandatory_language(config):
    # Case 2: JD requires Python and the user has it -> should pass
    job = JobPosting(
        id="2", title="Dev", company="A", location="B", url="C", site="D",
        description="Python is required."
    )
    user_skills = {"python", "docker"}

    result = hard_filter(job, user_skills, config)
    assert result.passed_hard_filter is True
    assert len(result.missing_skills) == 0

def test_passes_no_mandatory_requirements(config):
    # Case 3: JD has no mandatory requirements -> should pass
    job = JobPosting(
        id="3", title="Dev", company="A", location="B", url="C", site="D",
        description="We are looking for great developers."
    )
    user_skills = {"python"}

    result = hard_filter(job, user_skills, config)
    assert result.passed_hard_filter is True


def test_excludes_candidature_spontanee(config):
    config["ranking"] = {
        "exclude_keywords": ["candidature spontanée", "spontaneous application", "open candidate"]
    }
    job = JobPosting(
        id="4", title="Candidature Spontanée", company="A", location="B", url="C", site="D",
        description="Apply spontaneously."
    )
    result = hard_filter(job, {"python"}, config)
    assert result.passed_hard_filter is False


def test_excludes_spontaneous_application_en(config):
    config["ranking"] = {
        "exclude_keywords": ["candidature spontanée", "spontaneous application", "open candidate"]
    }
    job = JobPosting(
        id="5", title="Spontaneous Application", company="A", location="B", url="C", site="D",
        description="Apply now."
    )
    result = hard_filter(job, {"python"}, config)
    assert result.passed_hard_filter is False


def test_excludes_senior_sr(config):
    config["ranking"] = {"exclude_keywords": ["sr", "senior", "director"]}
    for title in ["Sr. GIS Engineer", "Senior Python Dev", "Director of Engineering"]:
        job = JobPosting(id="x", title=title, company="A", location="B", url="C", site="D", description="x")
        result = hard_filter(job, {"python"}, config)
        assert result.passed_hard_filter is False, f"'{title}' should be excluded"


def test_sr_whole_word_only(config):
    config["ranking"] = {"exclude_keywords": ["sr"]}
    job = JobPosting(id="x", title="Sri Lanka Office", company="A", location="B", url="C", site="D", description="x")
    result = hard_filter(job, {"python"}, config)
    assert result.passed_hard_filter is True, "'Sri Lanka' should NOT be excluded by 'sr'"


def test_excludes_defense_companies(config):
    config["hard_filter"]["exclude_company_patterns"] = ["défense", "defense", "armée", "military"]
    for company in ["Ministère de la Défense", "Délégation Générale armée", "Defense Corp", "Military Systems"]:
        job = JobPosting(id="x", title="Engineer", company=company, location="B", url="C", site="D", description="x")
        result = hard_filter(job, {"python"}, config)
        assert result.passed_hard_filter is False, f"'{company}' should be excluded"
