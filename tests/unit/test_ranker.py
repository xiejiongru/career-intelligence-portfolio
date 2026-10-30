from pipeline.utils.ranker import create_job_key, deduplicate_jobs, is_duplicate


class TestRanker:
    def test_create_job_key_deterministic(self):
        job = {"title": "GIS Engineer", "company": "Company B", "location": "Paris"}
        key1 = create_job_key(job)
        key2 = create_job_key(job)
        assert key1 == key2
        assert len(key1) == 12

    def test_is_duplicate_same_job(self):
        a = {"title": "Python Developer", "company": "Company A"}
        b = {"title": "Python Developer", "company": "Company A"}
        assert is_duplicate(a, b) is True

    def test_is_duplicate_different_job(self):
        a = {"title": "GIS Engineer", "company": "Company B"}
        b = {"title": "Python Developer", "company": "Company A"}
        assert is_duplicate(a, b) is False

    def test_deduplicate_jobs(self):
        jobs = [
            {"title": "GIS Engineer", "company": "Company B", "location": "Paris"},
            {"title": "GIS Engineer", "company": "Company B", "location": "Paris"},
            {"title": "Python Dev", "company": "Company A", "location": "Lyon"},
        ]
        deduped = deduplicate_jobs(jobs)
        assert len(deduped) == 2
