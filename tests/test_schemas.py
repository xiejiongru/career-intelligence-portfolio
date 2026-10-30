"""
Unit tests for Pydantic Schemas (Structured LLM Output)
=======================================================
Tests the cleaning and validation logic in schemas.py
"""
import pytest

from pipeline.matching.schemas import (
    ExtractedJob,
    JobRankingResult,
    _clean_json_string,
    parse_json_list,
    safe_parse_json,
)

# ── _clean_json_string ────────────────────────────────────────────────────────

class TestCleanJsonString:
    def test_strips_markdown_fence(self):
        raw = '```json\n{"score": 8}\n```'
        assert _clean_json_string(raw) == '{"score": 8}'

    def test_strips_prefix_text_before_brace(self):
        raw = 'Here is the JSON: {"score": 7}'
        assert _clean_json_string(raw) == '{"score": 7}'

    def test_strips_explanatory_prefix_before_brace(self):
        raw = 'Here is the result:  \n  {"score": 9}'
        assert _clean_json_string(raw) == '{"score": 9}'

    def test_handles_single_quotes(self):
        raw = "{'score': 8, 'reason': 'good'}"
        cleaned = _clean_json_string(raw)
        # After replacement, quotes are now valid JSON
        import json
        data = json.loads(cleaned)
        assert data["score"] == 8

    def test_handles_trailing_comma(self):
        raw = '{"score": 8, "reason": "ok", }'
        cleaned = _clean_json_string(raw)
        import json
        data = json.loads(cleaned)
        assert data["score"] == 8

    def test_handles_trailing_text_after_brace(self):
        raw = '{"score": 8}  \n\n  Some explanation here'
        cleaned = _clean_json_string(raw)
        import json
        data = json.loads(cleaned)
        assert data["score"] == 8

    def test_strips_bare_json_array(self):
        raw = '```json\n[{"id": "a"}, {"id": "b"}]\n```'
        assert _clean_json_string(raw) == '[{"id": "a"}, {"id": "b"}]'


# ── safe_parse_json ───────────────────────────────────────────────────────────

class TestSafeParseJson:
    def test_valid_json(self):
        raw = '{"score": 8, "reason": "Good match", "deal_breakers": ["Kubernetes"]}'
        result = safe_parse_json(raw, JobRankingResult)
        assert result is not None
        assert result.score == 8
        assert result.reason == "Good match"
        assert "Kubernetes" in result.deal_breakers

    def test_with_markdown_fence(self):
        raw = '```json\n{"score": 7, "reason": "Nice", "deal_breakers": []}\n```'
        result = safe_parse_json(raw, JobRankingResult)
        assert result is not None
        assert result.score == 7

    def test_with_prefix_explanation(self):
        raw = 'Here is the JSON:\n{"score": 6, "reason": "OK", "deal_breakers": []}'
        result = safe_parse_json(raw, JobRankingResult)
        assert result is not None
        assert result.score == 6

    def test_with_single_quotes(self):
        raw = "{'score': 5, 'reason': 'Average', 'deal_breakers': []}"
        result = safe_parse_json(raw, JobRankingResult)
        assert result is not None
        assert result.score == 5

    def test_with_trailing_comma(self):
        raw = '{"score": 8, "reason": "Good", "deal_breakers": [], }'
        result = safe_parse_json(raw, JobRankingResult)
        assert result is not None
        assert result.score == 8

    def test_score_coerced_from_string(self):
        raw = '{"score": "8", "reason": "Good", "deal_breakers": []}'
        result = safe_parse_json(raw, JobRankingResult)
        assert result is not None
        assert result.score == 8

    def test_totally_invalid_returns_none(self):
        raw = 'not json at all!!!'
        result = safe_parse_json(raw, JobRankingResult)
        assert result is None


# ── ExtractedJob validators ───────────────────────────────────────────────────

class TestExtractedJob:
    def test_job_type_normalization(self):
        job = ExtractedJob(
            id="test-1", title="DevOps Engineer", company="Acme",
            location="Paris", description="desc", url="https://x.com"
        )
        # job_type not provided → None
        assert job.job_type is None

    def test_job_type_cdi(self):
        job = ExtractedJob(
            id="test-2", title="DevOps", company="Acme",
            location="Paris", description="d", url="https://x.com",
            job_type="cdi"
        )
        assert job.job_type == "CDI"

    def test_job_type_stage(self):
        job = ExtractedJob(
            id="test-3", title="Intern", company="Acme",
            location="Paris", description="d", url="https://x.com",
            job_type="internship"
        )
        assert job.job_type == "Stage"

    def test_job_type_alternance(self):
        for raw in ("alternance", "Alternance", "ALTERNANCE"):
            job = ExtractedJob(
                id="t", title="T", company="C",
                location="P", description="d", url="https://x.com",
                job_type=raw
            )
            assert job.job_type == "Alternance", f"Failed for {raw!r}"

    def test_remote_yes(self):
        for raw in ("yes", "remote", "télétravail", "FULL REMOTE"):
            job = ExtractedJob(
                id="t", title="T", company="C",
                location="P", description="d", url="https://x.com",
                remote=raw
            )
            assert job.remote == "Yes", f"Failed for {raw!r}"

    def test_remote_partial(self):
        for raw in ("partial", "hybrid", "Hybrid", "partiel"):
            job = ExtractedJob(
                id="t", title="T", company="C",
                location="P", description="d", url="https://x.com",
                remote=raw
            )
            assert job.remote == "Partial", f"Failed for {raw!r}"

    def test_remote_no(self):
        for raw in ("no", "non", "onsite", "sur site"):
            job = ExtractedJob(
                id="t", title="T", company="C",
                location="P", description="d", url="https://x.com",
                remote=raw
            )
            assert job.remote == "No", f"Failed for {raw!r}"


# ── parse_json_list ───────────────────────────────────────────────────────────

class TestParseJsonList:
    def test_valid_list(self):
        raw = '[{"id": "a", "title": "T", "company": "C", "location": "P", "description": "d", "url": "https://x.com"}]'
        results = parse_json_list(raw, ExtractedJob)
        assert len(results) == 1
        assert results[0].id == "a"

    def test_with_markdown_fence(self):
        raw = '```json\n[{"id": "b", "title": "X", "company": "Y", "location": "Z", "description": "d", "url": "https://x.com"}]\n```'
        results = parse_json_list(raw, ExtractedJob)
        assert len(results) == 1

    def test_with_wrapped_dict(self):
        # Some LLMs return {"jobs": [...]} instead of a bare array
        raw = '{"jobs": [{"id": "c", "title": "A", "company": "B", "location": "P", "description": "d", "url": "https://x.com"}]}'
        results = parse_json_list(raw, ExtractedJob)
        assert len(results) == 1

    def test_partial_invalid_items_skipped(self):
        # First item valid, second missing required fields → skip it
        raw = '[{"id": "good", "title": "T", "company": "C", "location": "P", "description": "d", "url": "https://x.com"}, {"id": ""}]'
        results = parse_json_list(raw, ExtractedJob)
        assert len(results) == 1
        assert results[0].id == "good"

    def test_empty_list(self):
        raw = '[]'
        results = parse_json_list(raw, ExtractedJob)
        assert results == []

    def test_not_a_list_returns_empty(self):
        raw = '{"score": 8}'
        results = parse_json_list(raw, ExtractedJob)
        assert results == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
