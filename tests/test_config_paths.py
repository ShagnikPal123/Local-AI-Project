"""Guard against the launch-directory bug that silently disabled every API key.

`config.py` used to call `load_dotenv(".env.local")` with a CWD-relative path,
and ~14 stores defaulted to bare relative filenames. Starting the app from the
parent folder therefore loaded no credentials and created a second, empty set of
state files. The user-visible symptom was the assistant replying with the same
canned sentence to every question.

These tests fail if anyone reintroduces a relative default.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import paths

PROJECT_DIR = Path(__file__).resolve().parent.parent


def test_project_dir_is_the_source_tree():
    assert paths.PROJECT_DIR == PROJECT_DIR
    assert (paths.PROJECT_DIR / "server.py").exists()


def test_data_path_is_absolute_and_anchored():
    target = paths.data_path("example.json")
    assert target.is_absolute()
    assert target.parent == paths.DATA_DIR


def test_env_files_are_absolute():
    for candidate in paths.env_files():
        assert candidate.is_absolute(), f"{candidate} is not absolute"


def test_nyx_data_dir_env_var_redirects_state(tmp_path, monkeypatch):
    """The override is what lets tests and side-by-side installs stay separate."""
    monkeypatch.setenv("NYX_DATA_DIR", str(tmp_path))
    import importlib

    reloaded = importlib.reload(paths)
    try:
        assert reloaded.DATA_DIR == tmp_path.resolve()
        assert reloaded.data_path("chats.json").parent == tmp_path.resolve()
    finally:
        monkeypatch.delenv("NYX_DATA_DIR", raising=False)
        importlib.reload(paths)


def test_store_defaults_do_not_depend_on_the_working_directory():
    """Every persistent store must resolve to the same file from any CWD.

    Run in a subprocess from the *parent* directory, which is the exact
    condition that broke: `.vscode/settings.json` makes the parent the workspace
    root, so Run/F5 launched with that CWD.
    """
    probe = (
        "import sys, json;"
        f"sys.path.insert(0, {str(PROJECT_DIR)!r});"
        "from chat_sessions import ChatSessionStore;"
        "from memory import MemoryStore;"
        "from auth import AuthStore;"
        "import secret_store;"
        "print(json.dumps({"
        "'chats': str(ChatSessionStore().path),"
        "'memory': str(MemoryStore().path),"
        "'auth': str(AuthStore().path),"
        "'secrets': str(secret_store._STORE),"
        "}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(PROJECT_DIR.parent),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    resolved = json.loads(result.stdout.strip().splitlines()[-1])
    for name, value in resolved.items():
        assert Path(value).parent == PROJECT_DIR, (
            f"{name} resolved to {value!r} when launched from the parent folder; "
            "it must be anchored to the project directory"
        )


def test_api_keys_load_when_launched_from_the_parent_directory():
    """The original bug, stated directly."""
    probe = (
        "import sys;"
        f"sys.path.insert(0, {str(PROJECT_DIR)!r});"
        "from config import SETTINGS;"
        "print('HASKEY' if (SETTINGS.gemini_api_key or SETTINGS.openai_api_key "
        "or SETTINGS.anthropic_api_key or SETTINGS.groq_api_key) else 'NOKEY')"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(PROJECT_DIR.parent),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    verdict = result.stdout.strip().splitlines()[-1]
    if not (PROJECT_DIR / ".env.local").exists():
        return  # Nothing configured on this machine; nothing to assert.
    assert verdict == "HASKEY", (
        "config.py loaded no API key when started from the parent directory - "
        "the CWD-relative dotenv bug has been reintroduced"
    )


import json  # noqa: E402  (kept at the bottom; the probe strings above read better first)
