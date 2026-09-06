"""Tests for connectivity check caching."""

from unittest.mock import MagicMock, patch

from connectivity import clear_connectivity_cache, is_online


def test_is_online_uses_cached_result():
    clear_connectivity_cache()

    mock_sock = MagicMock()
    with patch("socket.create_connection", return_value=mock_sock) as mock_conn:
        assert is_online(force_refresh=True) is True
        assert mock_conn.call_count == 1
