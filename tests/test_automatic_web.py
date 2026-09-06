"Tests for automatic online research controls."""

from unittest.mock import patch
from web_access import answer, set_enabled

def test_answer_uses_fetched_sources():
    with patch("web_access.search_results", return_value=[{"title": "Docs", "url": "https://example.com"}]), patch("web_access.fetch", return_value="Current answer source"):
        set_enabled(True)
        assert "Current answer source" in answer("current question")

def test_answer_is_blocked_when_offline_mode_is_selected():
    set_enabled(False)
    try:
        with patch("web_access.is_online", return_value=True):
            try:
                answer("question")
                assert False
            except RuntimeError as error:
                assert "disabled" in str(error)
    finally:
        set_enabled(True)
