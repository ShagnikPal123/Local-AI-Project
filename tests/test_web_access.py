"Tests for permission-aware web tools."""

from unittest.mock import patch, MagicMock
import pytest
from web_access import fetch, search, set_enabled

def test_search_requires_permission():
    set_enabled(False)
    with pytest.raises(RuntimeError, match="disabled"):
        search("python")
    set_enabled(True)


def test_fetch_rejects_non_http_urls():
    with pytest.raises(ValueError, match="Only http"):
        fetch("file:///secret.txt")


def test_search_parses_result_links():
    html = '<a class="result__a" href="https://example.com">Example <b>page</b></a>'
    response = MagicMock(text=html)
    response.raise_for_status.return_value = None
    with patch("web_access.is_online", return_value=True), patch("web_access.requests.get", return_value=response):
        set_enabled(True)
        assert "Example page: https://example.com" in search("example")
