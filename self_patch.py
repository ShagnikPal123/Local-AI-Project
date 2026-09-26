"""Turn an approved self-improvement proposal into a real, tested, reversible edit.

The improvement engine files *descriptions* ("make X retry on timeouts"). When
the owner has authorised auto-approval, the autopilot hands each approved one
here, and this module:

1. finds the target file and refuses the ones that guard everything else
   (permissions, secrets, auth, the review gate, the autopilot itself);
2. asks the ``code_generation`` model for exact search/replace edits (JSON), and
   checks every ``old`` text occurs exactly once and the result still compiles;
3. applies the edit to a **sandbox copy** of the project and runs the tests that
   exercise that module there (or the whole suite at ``test_depth="full"``);
4. only if they pass, writes the edit into the live file — and only if the live
   file is byte-for-byte what the model saw — keeping the before/after text so
   :func:`rollback` restores it exactly.

Nothing here runs unless a proposal was approved (by the owner, or by an
auto-approve window the owner started).

The work is split in two so a reviewer can read the *real* edit before it lands:
:func:`prepare` (model edit + sandbox tests, live file untouched) and :func:`commit`
(write + backup). Before 2026-09-16 the autopilot's critic only ever saw a
description with empty content and blocked 94 of 101 changes as "diff missing".
Tests that already fail without the edit are not blamed on it: a red run is
compared with the same tests on the unedited sandbox.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from paths import PROJECT_DIR, data_path

#: Files the autopilot may never edit: they decide what everything else may do.
PROTECTED_FILES = frozenset({
    "permissions.py", "secret_store.py", "auth.py", "server_auth.py", "access_keys.py", "routes_access.py",
    "change_review.py", "improve_autopilot.py", "self_patch.py", "improvement_engine.py", "paths.py",
    "launcher.py", "conftest.py", "setup_nyx.py", "build_release.py",
})
#: Package folders whose modules count as base code.
CODE_DIRS = ("", "providers", "connectors", "core")

_SYNC_SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "frontend", "site", "dist", "build", "logs", "uploads", "tts_cache",
    "Real Nyx", "_preview", "_archive", "voice_tmp", "attachments", "checkpoints", "training", "learning",
    "client_state", "autopilot", "openai_mcp", "openai_mcp - Copy", "__pycache__", ".pytest_cache", "design",
    "docs", "local_pytest_tmp", "local_pytest_tmp - Copy", "system", "brain", "design_studio", "models",
})
_SYNC_SUFFIXES = frozenset({".py", ".json", ".md", ".ini", ".txt", ".toml", ".cfg", ".yaml", ".yml"})
_SYNC_MAX_BYTES = 5 * 1024 * 1024

ModelFn = Callable[..., str]


class PatchError(RuntimeError):
    """Why a proposal was not implemented, in words for the change record."""


@dataclass
class PatchResult:
    ok: bool
    change_id: str
    file: str = ""
    summary: str = ""
    diff: str = ""
    tests: str = ""
    error: str = ""
    seconds: float = 0.0
    edits: int = 0
    #: Set by prepare() and read by commit(); never sent to the UI.
    before: str = field(default="", repr=False)
    after: str = field(default="", repr=False)
    relative: str = field(default="", repr=False)
    already_failing: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in ("ok", "change_id", "file", "summary", "diff", "tests", "error", "seconds", "edits")}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sandbox_dir() -> Path:
    override = os.getenv("NYX_SANDBOX_DIR", "").strip()
    return Path(override) if override else Path(tempfile.gettempdir()) / "nyx-autopilot-sandbox"


def resolve_target(name: str, root: Path = PROJECT_DIR) -> Path:
    """The live file a proposal names (``router.py``, ``providers/gemini_provider.py``)."""
    clean = (name or "").strip().strip("`'\"").replace("\\", "/")
    if not clean.endswith(".py") or ".." in clean.split("/"):
        raise PatchError(f"{name!r} is not a Python module in the project.")
    base = clean.split("/")[-1]
    if base in PROTECTED_FILES:
        raise PatchError(f"{base} is protected: it guards permissions, secrets or the review gate itself.")
    candidates = []
    if "/" in clean:
        candidates.append(root / clean)
    candidates += [root / folder / base if folder else root / base for folder in CODE_DIRS]
    for candidate in candidates:
        if candidate.is_file() and candidate.resolve().is_relative_to(root.resolve()):
            return candidate
    raise PatchError(f"No module named {base} in the base code.")


def _read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def _write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".nyxtmp")
    with open(tmp, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Edits from the model
# ---------------------------------------------------------------------------


def edit_prompt(change: Dict[str, Any], relative: str, source: str, feedback: str = "") -> str:
    retry = (f"A previous attempt at this failed — fix exactly this and try again:\n{feedback[:1500]}\n\n"
             if feedback else "")
    return (
        "You are implementing one approved improvement to an AI assistant's own Python code.\n"
        f"Improvement: {change.get('title', '')}\n"
        f"Details: {change.get('description', '')}\n"
        f"File: {relative}\n\n{retry}"
        "Reply with JSON only, no prose, in exactly this shape:\n"
        '{"summary": "<one sentence of what you changed>", "edits": [{"old": "<exact existing text>", "new": "<replacement>"}]}\n\n'
        "Rules: each \"old\" must be copied exactly from the file and appear in it exactly once (include enough "
        "surrounding lines to be unique). Keep edits small and focused; do not reformat unrelated code; keep "
        "public function names and signatures working; never weaken security or delete tests. If the improvement "
        "is not worth doing or not possible safely, reply {\"summary\": \"skip: <reason>\", \"edits\": []}.\n\n"
        f"--- {relative} ---\n{source}"
    )


def parse_edits(reply: str) -> Tuple[str, List[Dict[str, str]]]:
    text = reply or ""
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    body = fence.group(1) if fence else text
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        raise PatchError("The model did not return edits as JSON.")
    try:
        data = json.loads(body[start:end + 1])
    except json.JSONDecodeError as error:
        raise PatchError(f"The model's edits were not valid JSON ({error.msg}).") from error
    edits = [e for e in data.get("edits", []) if isinstance(e, dict) and isinstance(e.get("old"), str) and isinstance(e.get("new"), str)]
    return str(data.get("summary", ""))[:300], edits


def apply_edits(source: str, edits: List[Dict[str, str]], max_changed_lines: int = 200) -> str:
    """Exact, unique search/replace. Raises PatchError on anything ambiguous."""
    if not edits:
        raise PatchError("No edits to apply.")
    crlf = "\r\n" in source
    result = source
    for index, edit in enumerate(edits, 1):
        old, new = edit["old"], edit["new"]
        if crlf:
            old = old.replace("\r\n", "\n").replace("\n", "\r\n")
            new = new.replace("\r\n", "\n").replace("\n", "\r\n")
        if not old.strip():
            raise PatchError(f"Edit {index} has empty search text.")
        count = result.count(old)
        if count != 1:
            raise PatchError(f"Edit {index}'s search text appears {count} times (must be exactly once).")
        result = result.replace(old, new, 1)
    changed = sum(1 for line in difflib.unified_diff(source.splitlines(), result.splitlines(), lineterm="", n=0)
                  if line[:1] in "+-" and not line.startswith(("+++", "---")))
    if changed > max_changed_lines:
        raise PatchError(f"The edit changes {changed} lines; the limit is {max_changed_lines}.")
    try:
        compile(result, "<patched>", "exec")
    except SyntaxError as error:
        raise PatchError(f"The patched file does not compile: {error.msg} (line {error.lineno}).") from error
    return result


def unified_diff(before: str, after: str, relative: str) -> str:
    return "".join(difflib.unified_diff(before.replace("\r\n", "\n").splitlines(True), after.replace("\r\n", "\n").splitlines(True),
                                        fromfile=f"a/{relative}", tofile=f"b/{relative}"))[:20000]


# ---------------------------------------------------------------------------
# Sandbox + tests
# ---------------------------------------------------------------------------


def sync_sandbox(root: Path = PROJECT_DIR, target: Optional[Path] = None) -> Path:
    """Mirror the source files (not data, not the venv) into the sandbox; copies only what changed."""
    target = target or sandbox_dir()
    target.mkdir(parents=True, exist_ok=True)
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SYNC_SKIP_DIRS and not d.startswith(".") and not d.startswith("local_pytest")]
        rel = Path(folder).relative_to(root)
        for name in files:
            source = Path(folder) / name
            if source.suffix not in _SYNC_SUFFIXES:
                continue
            try:
                stat = source.stat()
            except OSError:
                continue
            if stat.st_size > _SYNC_MAX_BYTES:
                continue
            dest = target / rel / name
            try:
                existing = dest.stat()
                if existing.st_size == stat.st_size and int(existing.st_mtime) >= int(stat.st_mtime):
                    continue
            except OSError:
                pass
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
    return target


def select_tests(module_stem: str, tests_dir: Path, limit: int = 12) -> List[str]:
    """Test files that name or import the module."""
    if not tests_dir.is_dir():
        return []
    chosen: List[str] = []
    pattern = re.compile(rf"^\s*(?:import|from)\s+(?:[\w.]+\.)?{re.escape(module_stem)}\b", re.MULTILINE)
    for path in sorted(tests_dir.glob("test_*.py")):
        if module_stem in path.stem:
            chosen.append(path.name)
            continue
        try:
            if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                chosen.append(path.name)
        except OSError:
            continue
    return chosen[:limit]


_FAILED_RE = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.MULTILINE)


def failed_tests(output: str) -> List[str]:
    """Test ids pytest reported as failed or errored ("FAILED tests/x.py::test_y - …")."""
    return sorted(set(_FAILED_RE.findall(output or "")))


def run_tests(sandbox: Path, selected: List[str], full: bool, timeout: int) -> Tuple[bool, str]:
    # No -x: comparing against the unedited code needs every failure, not the first. Warnings are off because
    # pytest prints them last, and the old 12-line tail showed only a FastAPI deprecation notice instead of
    # the test that failed.
    args = [sys.executable, "-m", "pytest", "-q", "-rfE", "--maxfail=40", "-p", "no:cacheprovider", "-p", "no:warnings",
            "--basetemp", str(sandbox / "_pytest_tmp")]
    args += [] if full or not selected else [f"tests/{name}" for name in selected]
    env = {**os.environ, "NYX_DATA_DIR": str(sandbox / "_data"), "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        result = subprocess.run(args, cwd=sandbox, capture_output=True, text=True, timeout=timeout, env=env,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return False, f"Tests timed out after {timeout}s."
    lines = (result.stdout or "").strip().splitlines()
    failures = [line for line in lines if line.startswith(("FAILED ", "ERROR "))][:40]
    tail = "\n".join(failures + [line for line in lines[-6:] if line not in failures])
    return result.returncode == 0, tail or (result.stderr or "")[-1200:]


# ---------------------------------------------------------------------------
# The whole thing
# ---------------------------------------------------------------------------


def _applied_path() -> Path:
    return data_path("autopilot/applied.json")


def _load_applied() -> Dict[str, Any]:
    try:
        return json.loads(_applied_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_applied(data: Dict[str, Any]) -> None:
    path = _applied_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _default_model_fn(prompt: str, *, system: str = "", max_tokens: int = 4000, **_kw: Any) -> str:
    from model_roles import MODEL_ROLES

    return MODEL_ROLES.run("code_generation", prompt, system=system, max_tokens=max_tokens).text


def prepare(change: Dict[str, Any], *, model_fn: Optional[ModelFn] = None, test_depth: str = "quick",
            max_changed_lines: int = 200, root: Path = PROJECT_DIR, sandbox: Optional[Path] = None,
            test_runner: Optional[Callable[[Path, List[str], bool, int], Tuple[bool, str]]] = None,
            feedback: str = "") -> PatchResult:
    """Write the edit and prove it in the sandbox. The live file is not touched. Never raises."""
    started = time.time()
    change_id = str(change.get("id") or change.get("change_id") or "")
    result = PatchResult(ok=False, change_id=change_id)
    try:
        path = resolve_target(str(change.get("target") or ""), root)
        relative = path.relative_to(root).as_posix()
        result.file = result.relative = relative
        before = _read(path)
        if len(before) > 120_000:
            raise PatchError(f"{relative} is too large ({len(before) // 1000} KB) for a safe automatic edit.")
        reply = (model_fn or _default_model_fn)(
            edit_prompt(change, relative, before, feedback),
            system="You write minimal, correct Python edits as exact search/replace JSON.", max_tokens=6000)
        summary, edits = parse_edits(reply)
        result.summary = summary
        if not edits:
            raise PatchError(summary or "The model chose not to change anything.")
        after = apply_edits(before, edits, max_changed_lines=max_changed_lines)
        result.edits = len(edits)
        result.diff = unified_diff(before, after, relative)

        runner = test_runner or run_tests
        box = sync_sandbox(root, sandbox)
        sandbox_file = box / relative
        sandbox_file.parent.mkdir(parents=True, exist_ok=True)
        full = test_depth == "full"
        selected = select_tests(path.stem, box / "tests")
        timeout = 1500 if full or not selected else 420
        _write(sandbox_file, after)
        try:
            passed, output = runner(box, selected, full or not selected, timeout)
        finally:
            _write(sandbox_file, before)  # the sandbox mirrors the live code again
        result.tests = output
        if not passed:
            with_edit = failed_tests(output)
            # The same tests without the edit: only failures the edit *adds* count against it.
            base_passed, base_output = runner(box, selected, full or not selected, timeout) if with_edit else (True, "")
            without_edit = failed_tests(base_output)
            if with_edit and not base_passed and set(with_edit) <= set(without_edit):
                result.already_failing = with_edit
                result.tests = (f"{len(with_edit)} test(s) already fail without this edit; the edit adds no new "
                                f"failures.\n{output}")
            else:
                new = sorted(set(with_edit) - set(without_edit))
                detail = ("New failures: " + ", ".join(new[:8]) + "\n") if new else ""
                raise PatchError("Tests failed with the edit, so it was not applied:\n" + detail + output[-1500:])
        result.before, result.after = before, after
        result.ok = True
    except PatchError as error:
        result.error = str(error)
    except Exception as error:  # noqa: BLE001 - a model or IO failure is a result, not a crash
        result.error = f"{type(error).__name__}: {error}"
    result.seconds = round(time.time() - started, 1)
    return result


def commit(result: PatchResult, root: Path = PROJECT_DIR) -> PatchResult:
    """Write a prepared, tested edit into the live file — only if nobody changed that file meanwhile."""
    started = time.time()
    try:
        if not result.ok or not result.after or not result.relative:
            raise PatchError(result.error or "Nothing prepared to apply.")
        path = root / result.relative
        before = result.before
        if _sha(_read(path)) != _sha(before):
            raise PatchError(f"{result.relative} changed while the edit was being tested; not applied.")
        _write(path, result.after)
        change_id = result.change_id
        backups = data_path(f"autopilot/backups/{change_id or int(started)}")
        backups.mkdir(parents=True, exist_ok=True)
        (backups / "before.txt").write_text(before, encoding="utf-8", newline="")
        (backups / "after.txt").write_text(result.after, encoding="utf-8", newline="")
        applied = _load_applied()
        applied[change_id] = {"file": result.relative, "before_sha": _sha(before), "after_sha": _sha(result.after),
                              "backup": str(backups), "applied_at": time.time(), "summary": result.summary}
        _save_applied(applied)
    except PatchError as error:
        result.ok, result.error = False, str(error)
    except Exception as error:  # noqa: BLE001
        result.ok, result.error = False, f"{type(error).__name__}: {error}"
    result.seconds = round(result.seconds + time.time() - started, 1)
    return result


def implement(change: Dict[str, Any], *, model_fn: Optional[ModelFn] = None, test_depth: str = "quick",
              max_changed_lines: int = 200, root: Path = PROJECT_DIR, sandbox: Optional[Path] = None,
              test_runner: Optional[Callable[[Path, List[str], bool, int], Tuple[bool, str]]] = None,
              feedback: str = "") -> PatchResult:
    """Implement one approved change: prepare, then commit when the tests allow. Never raises."""
    result = prepare(change, model_fn=model_fn, test_depth=test_depth, max_changed_lines=max_changed_lines, root=root,
                     sandbox=sandbox, test_runner=test_runner, feedback=feedback)
    return commit(result, root) if result.ok else result


def rollback(change_id: str, root: Path = PROJECT_DIR) -> str:
    """Put the file back exactly as it was — only if nobody has edited it since."""
    record = _load_applied().get(change_id)
    if not record:
        raise PatchError("That change was never applied to a file.")
    if record.get("rolled_back_at"):
        raise PatchError("That change was already rolled back.")
    path = root / record["file"]
    current = _read(path)
    if _sha(current) != record["after_sha"]:
        raise PatchError(f"{record['file']} has changed since the edit; roll back by hand to avoid losing those changes.")
    with open(Path(record["backup"]) / "before.txt", encoding="utf-8", newline="") as handle:
        before = handle.read()
    _write(path, before)
    applied = _load_applied()
    applied[change_id]["rolled_back_at"] = time.time()
    _save_applied(applied)
    return f"Restored {record['file']} to how it was before change {change_id}."


def applied_changes() -> Dict[str, Any]:
    return _load_applied()
