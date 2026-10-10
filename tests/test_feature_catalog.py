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


# --- what is running, however new it is (U31) -----------------------------------------------------------

import ast  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402

from paths import PROJECT_DIR  # noqa: E402

#: Names that are the engine itself, not background work (the launcher's server thread).
_THE_ENGINE_ITSELF = {"nyx-engine"}
_NOT_NYX_CODE = {"tests", "temp_inspect", "openai_mcp", "openai_mcp - Copy", "code_backups", "uploads", "AI_HANDOFF"}


def _nyx_source_files():
    """Nyx's own modules: the root files and every package folder, never the venv, tests or copies."""
    yield from PROJECT_DIR.glob("*.py")
    for folder in PROJECT_DIR.iterdir():
        if folder.is_dir() and folder.name not in _NOT_NYX_CODE and (folder / "__init__.py").exists():
            yield from folder.rglob("*.py")


def _thread_names_in_the_code():
    """The literal start of every ``Thread(name=...)`` in Nyx's code, and whether an id follows it."""
    found = {}
    for path in _nyx_source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            func = getattr(node, "func", None)
            if not isinstance(node, ast.Call) or getattr(func, "attr", getattr(func, "id", "")) != "Thread":
                continue
            for keyword in node.keywords:
                if keyword.arg != "name":
                    continue
                if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    found[keyword.value.value] = False
                elif isinstance(keyword.value, ast.JoinedStr):
                    head = ""
                    for part in keyword.value.values:
                        if not isinstance(part, ast.Constant):
                            break
                        head += str(part.value)
                    if head:
                        found[head] = True
    return found


def _wait_on(event):
    """A worker body that lives in this project (tests/ is inside it), like any feature's would."""
    event.wait(10)


class _Running:
    """A real thread for as long as the ``with`` lasts."""

    def __init__(self, name=None, target=_wait_on):
        self.release = threading.Event()
        self.thread = threading.Thread(target=target, args=(self.release,), name=name, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self.thread

    def __exit__(self, *exc):
        self.release.set()
        self.thread.join(5)


def test_the_code_really_starts_named_workers():
    names = _thread_names_in_the_code()
    assert {"nyx-research-", "nyx-absorb-", "nyx-idle-scheduler", "nyx-trading-autopilot"} <= set(names), names


@pytest.mark.parametrize("prefix,has_id", sorted(_thread_names_in_the_code().items()))
def test_every_named_worker_in_the_code_is_reported_in_words(prefix, has_id):
    """Fails the day a worker thread is started that the processes view cannot see or name.

    The names come from the source itself, so a feature added next month is checked too,
    and it passes without anyone editing a list, because the words are made from its name."""
    name = prefix + ("3f2a9c1b" if has_id else "")
    with _Running(name):
        rows = [row for row in feature_catalog.live_processes() if row["id"] == name]
    if prefix in _THE_ENGINE_ITSELF:
        assert rows == [], "the server's own thread is not background work"
        return
    # At least one: a real thread of the same name another test started may still be winding down (it was, in a
    # full run, for kahuna-lead). Every one shown must be named in words.
    assert rows, f"{name} is running but the processes view does not show it"
    for row in rows:
        label = row["label"]
        assert label != name and label[:1].isupper() and "_" not in label and "3f2a9c1b" not in label,             f"{name} shows as a raw name, not words: {row}"
        assert row["group"] in ("job", "service") and row["source"] == "thread"


def test_a_brand_new_worker_shows_with_words_made_from_its_name():
    with _Running("nyx-photo-sorter-9a8b7c6d"):
        row = next(row for row in feature_catalog.live_processes() if row["id"] == "nyx-photo-sorter-9a8b7c6d")
    assert row["label"] == "Photo sorter" and row["group"] == "job"


def test_an_unnamed_thread_running_nyx_code_still_shows_whose_code_it_is():
    with _Running() as thread:
        row = next(row for row in feature_catalog.live_processes() if row["id"] == thread.name)
    assert row["label"] == "Test feature catalog" and row["detail"] == "test_feature_catalog._wait_on"


def test_library_threads_are_plumbing_not_processes():
    release = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(release.wait, 5)
        time.sleep(0.05)
        rows = feature_catalog.live_processes()
        release.set()
    assert not any(row["id"].startswith("ThreadPoolExecutor") for row in rows)
    with _Running("some-library-thread", target=threading.Event.wait):
        assert not any(row["id"] == "some-library-thread" for row in feature_catalog.live_processes())


def test_always_on_loops_are_services_and_come_after_the_jobs():
    with _Running("nyx-idle-scheduler"), _Running("nyx-research-0a1b2c3d4e"):
        rows = feature_catalog.live_processes()
    groups = [row["group"] for row in rows]
    service = next(row for row in rows if row["id"] == "nyx-idle-scheduler")
    assert service["group"] == "service" and service["label"] == "Idle scheduler"
    assert groups == sorted(groups, key=lambda group: group == "service")


def test_a_job_its_module_reports_is_not_listed_again_as_its_thread(monkeypatch):
    module = types.ModuleType("pretend_research")
    module.background_status = lambda: [{"id": "0a1b2c3d4e", "label": "Research · standard", "tab": "research",
                                         "progress": 0.4, "seconds": 12}]
    monkeypatch.setitem(sys.modules, "pretend_research", module)
    with _Running("nyx-research-0a1b2c3d4e"):
        rows = [row for row in feature_catalog.live_processes() if "0a1b2c3d4e" in row["id"]]
    assert len(rows) == 1 and rows[0]["source"] == "module"
    assert rows[0]["tab"] == "research" and rows[0]["progress"] == 0.4 and rows[0]["seconds"] == 12


def test_a_feature_inside_a_package_is_heard(monkeypatch):
    """``finance_lab.simulator`` answered background_status and was skipped for living in a package."""
    module = types.ModuleType("finance_lab.pretend_sim")
    module.__file__ = str(PROJECT_DIR / "finance_lab" / "pretend_sim.py")
    module.background_status = lambda: [{"label": "Finance simulator", "detail": "day 3 of 30"}]
    monkeypatch.setitem(sys.modules, "finance_lab.pretend_sim", module)
    library = types.ModuleType("somelib.worker")
    library.__file__ = str(PROJECT_DIR / ".venv" / "Lib" / "site-packages" / "somelib" / "worker.py")
    library.background_status = lambda: [{"label": "Not ours"}]
    monkeypatch.setitem(sys.modules, "somelib.worker", library)

    labels = [row["label"] for row in feature_catalog.live_processes()]
    assert "Finance simulator" in labels and "Not ours" not in labels


def test_big_kahuna_training_runs_in_its_own_process_and_still_shows(monkeypatch):
    from identity0 import jobs

    monkeypatch.setattr(jobs, "list_jobs", lambda limit=30: [
        {"id": "train_nano-1a2b3c4d", "kind": "train_nano", "state": "running", "progress": 0.4,
         "message": "step 40 of 100", "started": time.time() - 60, "pid": 4242},
        {"id": "corpus-5e6f7a8b", "kind": "corpus", "state": "done", "progress": 1.0, "message": "", "started": 1, "pid": 1},
    ])
    rows = [row for row in feature_catalog.live_processes() if row["kind"] == "kahuna_job"]
    assert [row["label"] for row in rows] == ["Big Kahuna · train nano"]
    assert rows[0]["tab"] == "kahuna" and rows[0]["progress"] == 0.4 and rows[0]["seconds"] >= 59


def test_a_child_process_nyx_started_is_seen():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        deadline = time.time() + 5
        rows = []
        while time.time() < deadline and not rows:
            rows = [row for row in feature_catalog.live_processes() if row.get("pid") == child.pid]
        assert rows and rows[0]["source"] == "subprocess" and rows[0]["label"].lower().startswith("python")
    finally:
        child.kill()
        child.wait(5)
