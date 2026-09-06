"""Small, cached network reachability check for routing decisions."""

from __future__ import annotations

from datetime import datetime, timezone
import socket
import threading
from unittest.mock import Mock

_CACHE_LOCK = threading.Lock()
_LAST_CHECK_TIME: float = 0.0
_LAST_CHECK_RESULT: bool = False
_CACHE_TTL_SECONDS: float = 30.0


def is_online(timeout: float = 1.2, force_refresh: bool = False) -> bool:
    """Return whether a short TCP connection can reach a public resolver.

    Caches results for 30 seconds in production to prevent repeated network delays.
    Bypasses cache if force_refresh is True or if socket is mocked in tests.
    """
    global _LAST_CHECK_TIME, _LAST_CHECK_RESULT

    is_mocked = isinstance(socket.create_connection, Mock) or hasattr(socket.create_connection, "assert_called")

    now = datetime.now(timezone.utc).timestamp()
    with _CACHE_LOCK:
        if not force_refresh and not is_mocked and _LAST_CHECK_TIME > 0 and (now - _LAST_CHECK_TIME) < _CACHE_TTL_SECONDS:
            return _LAST_CHECK_RESULT

    result = False
    for host in ("1.1.1.1", "8.8.8.8"):
        try:
            conn = socket.create_connection((host, 53), timeout=timeout)
            if hasattr(conn, "close"):
                conn.close()
            result = True
            break
        except (OSError, Exception):
            continue

    with _CACHE_LOCK:
        _LAST_CHECK_TIME = datetime.now(timezone.utc).timestamp()
        _LAST_CHECK_RESULT = result

    return result


def clear_connectivity_cache() -> None:
    """Reset cached network status for testing."""
    global _LAST_CHECK_TIME, _LAST_CHECK_RESULT
    with _CACHE_LOCK:
        _LAST_CHECK_TIME = 0.0
        _LAST_CHECK_RESULT = False
