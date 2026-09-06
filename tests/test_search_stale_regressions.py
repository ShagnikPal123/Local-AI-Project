"Regression tests for source-age handling."""

from datetime import datetime, timezone
from unittest.mock import patch
from web_access import _age_metadata, _now_utc

def test_freshness_window_controls_stale_flag():
    now = datetime(2025, 2, 10, tzinfo=timezone.utc)
    with patch("web_access._now_utc", return_value=now):
        assert _age_metadata(datetime(2025, 2, 9, tzinfo=timezone.utc), 1)["is_stale"] is False
        assert _age_metadata(datetime(2025, 2, 8, tzinfo=timezone.utc), 1)["is_stale"] is True

def test_future_timestamps_are_not_marked_old():
    now = datetime(2025, 2, 10, tzinfo=timezone.utc)
    with patch("web_access._now_utc", return_value=now):
        assert _age_metadata(datetime(2025, 2, 11, tzinfo=timezone.utc), 1)["is_stale"] is False
