"""Offline tests for the connectivity helper."""

from unittest.mock import patch

from connectivity import is_online


def test_is_online_returns_true_when_a_resolver_is_reachable():
    with patch("connectivity.socket.create_connection"):
        assert is_online() is True


def test_is_online_returns_false_when_all_resolvers_fail():
    with patch("connectivity.socket.create_connection", side_effect=OSError):
        assert is_online() is False

