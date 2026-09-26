"""Build the download: a zip anyone can unzip and start with one double-click.

    .venv/Scripts/python.exe build_release.py          -> dist/NyxIchos-Windows.zip

Why a zip of the source and not Nyx.exe
---------------------------------------
Windows Smart App Control blocks unsigned executables it has no reputation for,
and a PyInstaller build is exactly that: on the owner's own PC every start of
Nyx.exe was refused (CodeIntegrity event 3077). Signing would fix it but costs a
certificate. The bundle instead runs on Python's signed interpreter: the user
double-clicks ``Start Nyx.bat``, which installs Python for them if needed (winget,
per-user, no admin), installs the packages, creates the desktop shortcut and the
nyx:// link, and starts Nyx. Every later start is one click on "Nyx Ichos".

What goes in
------------
Everything git knows about (tracked, or untracked but not ignored) plus the built
web UI, which git ignores but a user without Node.js cannot build. Personal data
and credentials are excluded by name *and* the finished file list is scanned, so
a key that ends up in an unexpected file stops the build instead of shipping.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Iterable, List

PROJECT = Path(__file__).resolve().parent
OUTPUT = PROJECT / "dist" / "NyxIchos-Windows.zip"
TOP = "NyxIchos"

#: Never shipped, whatever git thinks. Owner data, credentials, caches, dev-only trees.
EXCLUDE = [
    ".env", ".env.local", ".env.*.local", "*.secrets.json", ".secrets.json",
    "auth.json", "chats.json", "memory.json", "tabs.json", "widgets.json", "widgets.json.bak",
    "skills.json", "provider_specs.json", "overlay.json", "speech_patterns.json",
    "voice_profile.json", "device_profile.json", "custom_personality.json", "access.json",
    "permissions.json", "email_accounts.json", "engine.json", "ui_state.json",
    "folder_registry.json", "local_storage.json", "custom_db.json", "deploy_payload.json",
    "tmp_*.json", "demo_memory.json",
    "logs/*", "uploads/*", "attachments/*", "checkpoints/*", "profiles/*", "voice_tmp/*",
    "tests/*", "design/*", "docs/*", "_preview/*", "_archive/*", "build/*", "dist/*",
    "local_pytest_tmp/*", "local_pytest_tmp - Copy/*", "openai_mcp/*", "openai_mcp - Copy/*",
    "Real Nyx/*", ".freebuff/*", ".vscode/*", ".claude/*", "training/*",
    "*.pyc", "*/__pycache__/*", "nyx.spec", "*.spec.bak", "site/*",
    "frontend/nyx-pulse/node_modules/*", "frontend/nyx-pulse/tsconfig.tsbuildinfo",
    "NYX_MODEL_ROUTINE.md", "CLAUDE_*.md", "OVERHAUL_CONTRACTS.md", "PROJECT_STATE.md",
    # Internal planning documents. NYX_WORKPLAN.md quotes the owner's original
    # request verbatim, and that request contained a live Obsidian token.
    "NYX_WORKPLAN.md", "ROADMAP.md", "COMPLETED.md", "AGENT.md", "KEYS_NEEDED.md",
    "IDEAS_OVERHAUL.md", "DESIGN_HANDOFF.md", "IDEAS_ROUND2.md",
    # The developers' handoff quotes the owner's requests word for word. Nyx reads it
    # only in the developer copy (handoff_tools says so when it is missing).
    "AI_HANDOFF/*",
]

#: A value after one of these names means a real secret is about to ship.
_SECRET_RE = re.compile(
    r"(?:API_KEY|SECRET|TOKEN|PASSWORD)\s*[=:]\s*['\"]?([A-Za-z0-9_\-\.]{20,})",
)

#: Credentials recognisable by shape alone, wherever they appear.
_RAW_TOKEN_RES = [
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),          # Google API keys
    re.compile(r"\bAQ\.[0-9A-Za-z_\-]{20,}"),         # newer Google key format
    re.compile(r"\bsk-(?:proj-)?[0-9A-Za-z_\-]{20,}"),  # OpenAI
    re.compile(r"\bsk-ant-[0-9A-Za-z_\-]{20,}"),      # Anthropic
    re.compile(r"\bnvapi-[0-9A-Za-z_\-]{20,}"),       # NVIDIA NIM
    re.compile(r"\bgsk_[0-9A-Za-z]{20,}"),            # Groq
    re.compile(r"\b[0-9a-f]{48,}\b"),                 # long hex tokens (e.g. Obsidian REST)
]
#: Files where the pattern is documentation of variable names, not values.
_SECRET_SCAN_SKIP = {".env.example"}

#: Published values that are shaped like tokens but are nobody's secret. Listed by
#: exact value, so a real key that merely sits in the same file still stops the build.
_PUBLIC_VALUES = {
    # SHA-256 of the EICAR antivirus test file, which file_guard.py matches by digest.
    "275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0f",
}

READ_ME = """Nyx Ichos — your local AI assistant
=====================================

1. Double-click  "Start Nyx.bat"  in this folder.

   The first time it sets everything up (a couple of minutes): it installs
   Python for you if you don't have it, installs Nyx, puts a "Nyx Ichos" icon on
   your desktop, and opens Nyx in your browser.

   If Windows asks "Do you want to run this file?", choose Run.

2. From then on, just double-click "Nyx Ichos" on your desktop — or let it start
   with Windows (it does by default; switch it off from the tray icon).

Nyx runs on this computer. Look for its icon near the clock: right-click it to
open Nyx, restart it, or quit.

Add a free AI key (Gemini works well) in Nyx's Models tab, or install Ollama to
run models locally with no key at all.
"""


def _git_files() -> List[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=PROJECT, capture_output=True, check=True,
    )
    names = [n for n in result.stdout.decode("utf-8", errors="replace").split("\0") if n]
    return [n for n in names if (PROJECT / n).is_file()]


def _excluded(relative: str) -> bool:
    posix = relative.replace("\\", "/")
    name = posix.rsplit("/", 1)[-1]
    for pattern in EXCLUDE:
        if fnmatch.fnmatch(posix, pattern) or ("/" not in pattern and fnmatch.fnmatch(name, pattern)):
            return True
    return False


def collect() -> List[str]:
    files = {f for f in _git_files() if not _excluded(f)}
    dist = PROJECT / "frontend" / "nyx-pulse" / "dist"
    if not (dist / "app" / "index.html").is_file():
        raise SystemExit("The web UI is not built. Run `npm run build` in frontend/nyx-pulse first.")
    for path in dist.rglob("*"):
        if path.is_file():
            files.add(path.relative_to(PROJECT).as_posix())
    for required in ("Start Nyx.bat", "launcher.py", "setup_nyx.py", "server.py", "requirements.txt"):
        if required not in files:
            raise SystemExit(f"Refusing to build: {required} would be missing from the bundle.")
    return sorted(files)


def _placeholder(value: str) -> bool:
    """Documentation examples like sk-proj-YOUR-KEY-HERE are not credentials."""
    upper = value.upper()
    return any(word in upper for word in ("YOUR", "HERE", "XXXX", "EXAMPLE", "PLACEHOLDER", "REDACTED"))


def scan_for_secrets(files: Iterable[str]) -> List[str]:
    """Return 'file: variable' for anything that looks like a real credential."""
    findings = []
    for relative in files:
        if relative.rsplit("/", 1)[-1] in _SECRET_SCAN_SKIP:
            continue
        path = PROJECT / relative
        if path.suffix.lower() in {".png", ".ico", ".jpg", ".jpeg", ".webp", ".gif", ".zip", ".woff", ".woff2"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in _SECRET_RE.finditer(text):
            value = match.group(1)
            # Placeholders and identifiers in code are not credentials.
            if value.isupper() or _placeholder(value) or value.startswith("test") or ("_" in value and value.islower()):
                continue
            findings.append(f"{relative}: …{value[-4:]}")
        for pattern in _RAW_TOKEN_RES:
            for match in pattern.finditer(text):
                if _placeholder(match.group(0)) or match.group(0) in _PUBLIC_VALUES:
                    continue
                findings.append(f"{relative}: token shaped like {pattern.pattern[:18]} …{match.group(0)[-4:]}")
    return findings


def build(output: Path = OUTPUT) -> Path:
    files = collect()
    leaks = scan_for_secrets(files)
    if leaks:
        raise SystemExit("Refusing to build — possible credentials found:\n  " + "\n  ".join(leaks))

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for relative in files:
            bundle.write(PROJECT / relative, f"{TOP}/{relative}")
        bundle.writestr(f"{TOP}/READ ME FIRST.txt", READ_ME.replace("\n", "\r\n"))
    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"  Built {output} — {len(files)} files, {size_mb:.1f} MB")
    return output


if __name__ == "__main__":
    build()
    sys.exit(0)
