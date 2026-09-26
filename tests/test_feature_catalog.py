"""The feature catalog finds features instead of being told about them."""

from __future__ import annotations

import sys
import types

import pytest

import feature_catalog


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(feature_catalog, "_store_path", lambda: tmp_path / "feature_catalog.json")
    monkeypatch.setattr(feature_catalog, "_cache", None, raising=False)
    monkeypatch.setattr(feature_catalog, "_cached_at", 0.0, raising=False)
    yield
    feature_catalog._cache = None


def test_a_scan_finds_the_real_tools_tabs_and_modules():
    catalog = feature_catalog.scan(force=True)
    assert catalog["counts"]["modules"] > 50           # this project is not small
    assert catalog["counts"]["tabs"] >= 1
    assert any(row["module"] == "feature_catalog.py" for row in catalog["modules"])


def test_every_module_carries_the_first_line_of_its_docstring():
    catalog = feature_catalog.scan(force=True)
    row = next(row for row in catalog["modules"] if row["module"] == "proto_voice.py")
    assert "always listening" in row["what"].lower()


def test_use_is_counted_and_survives_a_reread():
    feature_catalog.note("tool", "search_web")
    feature_catalog.note("tool", "search_web")
    assert feature_catalog.used("tool", "search_web") == 2
    assert feature_catalog.uses()["tool:search_web"]["count"] == 2


def test_a_new_module_is_reported_as_new(tmp_path, monkeypatch):
    feature_catalog.scan(force=True)                    # first look: everything is known
    real_modules = feature_catalog._modules

    def with_an_extra():
        return real_modules() + [{"module": "brand_new_thing.py", "what": "Something built later", "kb": 1.0}]

    monkeypatch.setattr(feature_catalog, "_modules", with_an_extra)
    catalog = feature_catalog.scan(force=True)
    assert "brand_new_thing.py" in catalog["new_modules"]


def test_anything_with_background_status_is_found_while_it_runs(monkeypatch):
    """The part that keeps working as Nyx grows: one function, and it shows up."""
    module = types.ModuleType("pretend_feature")
    module.background_status = lambda: [{"label": "Pretend job", "detail": "step 2 of 5", "running": True}]
    monkeypatch.setitem(sys.modules, "pretend_feature", module)

    running = feature_catalog.live_processes()
    assert any(row["label"] == "Pretend job" and row["detail"] == "step 2 of 5" for row in running)


def test_a_finished_job_is_not_reported_as_running(monkeypatch):
    module = types.ModuleType("pretend_finished")
    module.background_status = lambda: [{"label": "Old job", "running": False}]
    monkeypatch.setitem(sys.modules, "pretend_finished", module)

    assert not any(row["label"] == "Old job" for row in feature_catalog.live_processes())


def test_a_broken_probe_does_not_hide_the_rest(monkeypatch):
    module = types.ModuleType("pretend_broken")

    def explode():
        raise RuntimeError("no")

    module.background_status = explode
    monkeypatch.setitem(sys.modules, "pretend_broken", module)

    good = types.ModuleType("pretend_good")
    good.background_status = lambda: [{"label": "Still here", "running": True}]
    monkeypatch.setitem(sys.modules, "pretend_good", good)

    assert any(row["label"] == "Still here" for row in feature_catalog.live_processes())


def test_the_summary_reads_as_english():
    feature_catalog.note("tool", "search_web", 5)
    text = feature_catalog.summary()
    assert "tools" in text and "model roles" in text
    assert "search_web (5)" in text or "Running now" in text
