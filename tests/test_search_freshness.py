"Tests for search time awareness and source timestamps."""

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from web_access import _age_metadata, _parse_timestamp, search_results, set_enabled

def test_timestamp_is_parsed_and_age_is_reported():
    timestamp = _parse_timestamp("2025-01-01")
    assert timestamp is not None
    with patch("web_access._now_utc", return_value=datetime(2025, 1, 2, tzinfo=timezone.utc)):
        metadata = _age_metadata(timestamp)
    assert metadata["age"] == "1d"
    assert metadata["is_stale"] is False

def test_unknown_timestamp_is_marked_stale():
    assert _age_metadata(None)["is_stale"] is True

def test_google_result_keeps_published_timestamp():
    response = MagicMock(text="", headers={"content-type": "application/json"})
    response.json.return_value = {"items": [{"title": "News", "link": "https://example.com", "pagemap": {"metatags": [{"article:published_time": "2025-01-01"}]}}]}
    response.raise_for_status.return_value = None
    with patch("web_access.SETTINGS.google_api_key", "key"), patch("web_access.SETTINGS.google_cse_id", "cx"), patch("web_access.is_online", return_value=True), patch("web_access.requests.get", return_value=response):
        set_enabled(True)
        assert search_results("news", engine="google")[0]["published_at"] == "2025-01-01"
