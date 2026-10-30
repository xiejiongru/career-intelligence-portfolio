"""Unit tests for platform_scraper utility functions (_detect_blocked, _retry_request)."""
from pipeline.ingestion.platform_scraper import _detect_blocked


class TestDetectBlocked:

    def test_returns_none_for_clean_html(self):
        html = "<html><body>Welcome to our job board</body></html>"
        assert _detect_blocked(html) is None

    def test_detects_captcha(self):
        html = '<div class="recaptcha">please verify</div>'
        assert _detect_blocked(html) == "captcha"

    def test_detects_geo_block(self):
        html = "<title>Access Denied</title><p>not available in your region</p>"
        assert _detect_blocked(html) == "geo_block"

    def test_detects_cloudflare(self):
        html = '<div id="cf-browser-verification">Just a moment...</div>'
        assert _detect_blocked(html) == "cloudflare"

    def test_detects_radware(self):
        html = "<html>Radware Security Check</html>"
        assert _detect_blocked(html) == "radware"

    def test_detects_rate_limit(self):
        html = "<html>429 Too Many Requests</html>"
        assert _detect_blocked(html) == "rate_limit"

    def test_case_insensitive(self):
        html = "<html>CAPTCHA verification required</html>"
        assert _detect_blocked(html) == "captcha"

    def test_empty_html(self):
        assert _detect_blocked("") is None
        assert _detect_blocked(" ") is None
