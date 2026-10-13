"""Shared test setup: every test runs against a fresh, empty data folder and never the network.

``ICHOS_TRADER_DATA`` points the app's stores at a temporary folder, so a test can never touch a
real practice account. ``ICHOS_TRADER_OFFLINE=1`` makes the market hub use the built-in simulated
market instead of reaching for Yahoo, Coinbase or Kraken.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
for extra in (APP_ROOT, APP_ROOT / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))


@pytest.fixture(autouse=True)
def _isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("ICHOS_TRADER_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("ICHOS_TRADER_OFFLINE", "1")
    yield
