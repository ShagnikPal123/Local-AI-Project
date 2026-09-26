"""Nyx stays small on disk: caches and backups are trimmed, the owner's data is not (owner, 2026-09-15)."""

from __future__ import annotations

import os
import time

import storage_budget


def test_budgets_trim_backups_and_caches_but_never_memories_or_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_budget, "data_path", lambda name: tmp_path / name)
    monkeypatch.setattr(storage_budget, "PROJECT_DIR", tmp_path)
    monkeypatch.setitem(storage_budget.BUDGETS, "code_backups", {"max_mb": 1, "max_days": 30, "keep_newest": 2})
    monkeypatch.setitem(storage_budget.BUDGETS, "tts_cache", {"max_mb": 1})
    monkeypatch.setitem(storage_budget.BUDGETS, "learning_log_mb", 1)

    backups = tmp_path / "code_backups"
    backups.mkdir()
    for n in range(5):
        path = backups / f"b{n}.py"
        path.write_bytes(b"x" * 400_000)
        os.utime(path, (time.time() - 100 + n, time.time() - 100 + n))
    ancient = backups / "ancient.py"
    ancient.write_bytes(b"old")
    os.utime(ancient, (time.time() - 40 * 86400, time.time() - 40 * 86400))
    (tmp_path / "learning").mkdir()
    log = tmp_path / "learning" / "turns.jsonl"
    log.write_bytes(b"".join(f'{{"n": {n}}}\n'.encode() for n in range(150_000)))
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "photo.png").write_bytes(b"p" * 3_000_000)
    (tmp_path / "brain").mkdir()
    (tmp_path / "brain" / "brain.db").write_bytes(b"")

    result = storage_budget.enforce()
    left = sorted(p.name for p in backups.iterdir())
    assert "ancient.py" not in left and {"b3.py", "b4.py"} <= set(left)
    assert sum(p.stat().st_size for p in backups.iterdir()) <= 1024 * 1024
    assert log.stat().st_size <= 1024 * 1024 and log.read_bytes().endswith(b'{"n": 149999}\n')
    assert (tmp_path / "uploads" / "photo.png").exists()
    assert result["freed_total"] > 0


def test_only_listed_leftovers_can_be_removed(tmp_path, monkeypatch):
    target = tmp_path / "old_build"
    target.mkdir()
    (target / "Nyx.exe").write_bytes(b"MZ" * 1000)
    monkeypatch.setattr(storage_budget, "LEFTOVERS", {"old": {"path": target, "why": "test"}})
    monkeypatch.setattr(storage_budget, "data_path", lambda name: tmp_path / "data" / name)
    report = storage_budget.report()
    assert [item["id"] for item in report["leftovers"]] == ["old"] and report["reclaimable_bytes"] == 2000
    try:
        storage_budget.remove_leftover("../../Windows")
        raise AssertionError("an unlisted key was accepted")
    except KeyError:
        pass
    assert storage_budget.remove_leftover("old") == 2000 and not target.exists()
