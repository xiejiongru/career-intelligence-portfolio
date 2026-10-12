"""Tests for Thinking Kernel — multi-role critique loop."""
from pipeline.ingestion.models import JobPosting
from pipeline.matching.thinking_kernel import ThinkingKernel, ThinkingResult


def make_job(title="GIS Engineer", company="ACME", location="Paris",
             description="Working with Python, PostGIS, QGIS for geospatial data processing",
             site="linkedin", salary=None):
    return JobPosting(
        id=f"test-{title[:10].lower().replace(' ', '-')}",
        title=title,
        company=company,
        location=location,
        description=description,
        url="https://example.com/job",
        site=site,
        salary=salary,
    )


# ------------------------------------------------------------------
# Baseline
# ------------------------------------------------------------------
def test_baseline_score():
    kernel = ThinkingKernel()
    job = make_job()
    ctx = {"target_skills": ["python", "postgis", "qgis", "aws"]}
    score = kernel._baseline_score(job, ctx)
    assert score == 75.0  # 3 out of 4


def test_baseline_no_match():
    kernel = ThinkingKernel()
    job = make_job(description="Nothing about tech here.")
    ctx = {"target_skills": ["python", "docker"]}
    score = kernel._baseline_score(job, ctx)
    assert score == 0.0


# ------------------------------------------------------------------
# System Layer
# ------------------------------------------------------------------
def test_system_broad_coverage():
    kernel = ThinkingKernel()
    job = make_job(description="python postgis qgis aws docker kubernetes terraform")
    adj = kernel._system_layer(job, {"target_skills": ["python", "postgis", "qgis", "aws", "docker"]}, 50)
    deltas = [a.delta for a in adj]
    assert 5 in deltas


def test_system_narrow_coverage():
    kernel = ThinkingKernel()
    job = make_job(description="just python")
    adj = kernel._system_layer(job, {"target_skills": ["python", "postgis", "qgis", "aws"]}, 50)
    deltas = [a.delta for a in adj]
    assert -5 in deltas


def test_system_senior_bonus():
    kernel = ThinkingKernel()
    job = make_job(title="Senior GIS Engineer")
    adj = kernel._system_layer(job, {"target_skills": ["python", "gis"]}, 50)
    deltas = {a.delta for a in adj}
    assert 3 in deltas


def test_system_junior_penalty():
    kernel = ThinkingKernel()
    job = make_job(title="Junior GIS Developer")
    adj = kernel._system_layer(job, {"target_skills": ["python", "gis"]}, 50)
    deltas = {a.delta for a in adj}
    assert -10 in deltas


# ------------------------------------------------------------------
# Human Layer
# ------------------------------------------------------------------
def test_human_domain_alignment():
    kernel = ThinkingKernel()
    job = make_job(description="geomatics and remote sensing work with cartography")
    adj = kernel._human_layer(job, {"domain_keywords": ["geomatics", "remote sensing", "cartography"]}, 50)
    assert any(a.delta == 4 for a in adj)


def test_human_location_bonus():
    kernel = ThinkingKernel()
    job = make_job(location="Paris, France")
    adj = kernel._human_layer(job, {"allowed_locations": ["Paris", "France"]}, 50)
    assert any(a.delta == 3 for a in adj)


def test_human_location_penalty():
    kernel = ThinkingKernel()
    job = make_job(location="Berlin, Germany")
    adj = kernel._human_layer(job, {"allowed_locations": ["Paris", "France"]}, 50)
    assert any(a.delta == -3 for a in adj)


# ------------------------------------------------------------------
# Validation Layer
# ------------------------------------------------------------------
def test_validation_missing_fields():
    kernel = ThinkingKernel()
    job = make_job(description="")
    job.url = ""
    job.company = ""
    adj = kernel._validation_layer(job, {}, 50)
    assert any(a.delta <= -5 for a in adj)


def test_validation_salary_bonus():
    kernel = ThinkingKernel()
    job = make_job(salary="€60,000")
    adj = kernel._validation_layer(job, {}, 50)
    assert any(a.delta == 2 for a in adj)


# ------------------------------------------------------------------
# Critique Layer
# ------------------------------------------------------------------
def test_critique_buzzword_without_skills():
    kernel = ThinkingKernel()
    # "ai" is in "training", "blockchain" and "metaverse" are buzzwords
    # No real skills in description or title
    job = make_job(title="Platform Engineer", description="Leveraging AI blockchain metaverse solutions")
    adj = kernel._critique_layer(job, {"target_skills": ["python", "postgis"]}, 50)
    assert any(a.delta == -5 for a in adj)


def test_critique_no_buzzword_penalty():
    kernel = ThinkingKernel()
    job = make_job(description="python postgis aws deployment")
    adj = kernel._critique_layer(job, {"target_skills": ["python", "postgis"]}, 50)
    assert not any(a.delta == -5 for a in adj)


# ------------------------------------------------------------------
# Full evaluation
# ------------------------------------------------------------------
def test_full_evaluation():
    kernel = ThinkingKernel()
    job = make_job(
        title="Senior GIS Engineer",
        description="python postgis qgis geomatics remote sensing",
        location="Paris, France",
        salary="\u20ac65,000",
    )
    ctx = {
        "target_skills": ["python", "postgis", "qgis", "aws", "docker", "kubernetes"],
        "domain_keywords": ["geomatics", "remote sensing", "cartography"],
        "preferred_technologies": ["python", "postgis", "qgis", "aws"],
        "allowed_locations": ["Paris", "France"],
    }
    result = kernel.evaluate(job, ctx)
    assert isinstance(result, ThinkingResult)
    assert result.final_score > result.baseline_score  # bonuses outweigh penalties
    assert result.trace


def test_full_evaluation_poor_match():
    kernel = ThinkingKernel()
    job = make_job(
        title="Junior JavaScript Developer",
        description="React Node blockchain startup contract",
        location="Berlin",
    )
    ctx = {
        "target_skills": ["python", "postgis", "qgis"],
        "domain_keywords": ["geomatics", "gis"],
        "preferred_technologies": ["python", "postgis"],
        "allowed_locations": ["Paris", "France"],
    }
    result = kernel.evaluate(job, ctx)
    assert result.final_score < 30


def test_gis_company_bonus():
    kernel = ThinkingKernel()
    job = make_job(title="Software Engineer", company="TomTom", description="Build mapping platform")
    ctx = {"target_skills": ["python", "gis"], "domain_keywords": [], "preferred_technologies": [], "allowed_locations": []}
    result = kernel.evaluate(job, ctx)
    # TomTom is in GIS_COMPANIES → +15 bonus applied
    system_adjustments = [a for a in result.adjustments if a.layer == "system"]
    assert any("GIS/mapping company" in a.reason for a in system_adjustments)
    gis_bonus = next(a.delta for a in system_adjustments if "GIS/mapping" in a.reason)
    assert gis_bonus == 15


def test_non_gis_company_no_bonus():
    kernel = ThinkingKernel()
    job = make_job(title="Software Engineer", company="Google", description="Build search engine")
    ctx = {"target_skills": ["python", "gis"], "domain_keywords": [], "preferred_technologies": [], "allowed_locations": []}
    result = kernel.evaluate(job, ctx)
    assert not any("GIS/mapping company" in a.reason for a in result.adjustments)
