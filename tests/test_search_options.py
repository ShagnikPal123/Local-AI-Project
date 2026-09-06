"Tests for configurable search engines and freshness."""

from unittest.mock import MagicMock, patch
from web_access import search_results, set_enabled

def test_google_results_are_parsed():
    response = MagicMock(text="", headers={"content-type": "application/json"})
    response.json.return_value = {"items": [{"title": "Fresh", "link": "https://example.com"}]}
    response.raise_for_status.return_value = None
    with patch("web_access.SETTINGS.google_api_key", "key"), patch("web_access.SETTINGS.google_cse_id", "cx"), patch("web_access.is_online", return_value=True), patch("web_access.requests.get", return_value=response):
        set_enabled(True)
        assert search_results("news", engine="google")[0]["title"] == "Fresh"
