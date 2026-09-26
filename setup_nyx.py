"""One-time setup that turns a Nyx folder into a one-click app.

``Start Nyx.bat`` runs this after it has made sure Python and the packages are
in place. It is idempotent — running it again repairs anything missing and
changes nothing that is already right — so "run setup again" is always a safe
answer to "something is off".

What it does, all per-user (no administrator prompt anywhere):

1. checks the Python packages import, installing requirements.txt if not;
2. makes sure the web UI is built (a release bundle ships it prebuilt);
3. registers the ``nyx://`` link, so the website's Launch button and the app's
   Start button can start the engine;
4. creates "Nyx Ichos" shortcuts on the Desktop and in the Start Menu that start
   Nyx with no console window;
5. turns on start-with-Windows (``--no-autostart`` to skip; the tray icon and
   Settings can switch it off later);
6. starts Nyx and opens it.

``--uninstall`` undoes 3–5. It never touches chats, memory, keys or settings.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

import launcher
import paths

SHORTCUT_NAME = "Nyx Ichos"
#: Written into the venv once setup has completed, so ``Start Nyx.bat`` can take
#: its instant path (start and exit) on every later click.
READY_MARKER = "nyx-ready.txt"

#: Import names that prove the runtime is complete. fastapi/uvicorn are the
#: engine; the rest are the tray icon and machine access added in the overhaul.
REQUIRED_MODULES = ("fastapi", "uvicorn", "pydantic", "requests", "dotenv", "psutil", "PIL", "pystray")

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def say(message: str) -> None:
    print(f"  {message}", flush=True)


# ---------------------------------------------------------------------------
# 1. Packages
# ---------------------------------------------------------------------------


def missing_modules(modules: tuple[str, ...] = REQUIRED_MODULES) -> List[str]:
    missing = []
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception:
            missing.append(name)
    return missing


def requirements_digest() -> str:
    try:
        return hashlib.sha256(paths.project_path("requirements.txt").read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def ensure_packages() -> bool:
    missing = missing_modules()
    if not missing:
        say("Python packages: ready.")
        return True
    say(f"Installing Python packages (missing: {', '.join(missing)}) — this takes a minute, once...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-r",
         str(paths.project_path("requirements.txt"))],
        cwd=str(paths.PROJECT_DIR),
    )
    importlib.invalidate_caches()
    still = missing_modules()
    if result.returncode != 0 or still:
        say(f"PROBLEM: packages did not install ({', '.join(still) or 'pip failed'}). "
            "Check the internet connection and run Start Nyx.bat again.")
        return False
    say("Python packages: installed.")
    return True


# ---------------------------------------------------------------------------
# 2. Web UI
# ---------------------------------------------------------------------------


def ui_index() -> Path:
    return paths.project_path("frontend/nyx-pulse/dist/app/index.html")


def ensure_ui() -> bool:
    if ui_index().is_file():
        say("Workspace UI: ready.")
        return True
    npm = shutil.which("npm")
    if not npm:
        say("PROBLEM: the workspace UI is not built and Node.js is not installed. "
            "Download the release bundle (it includes the built UI) or install Node.js.")
        return False
    say("Building the workspace UI — this takes a minute, once...")
    front = paths.project_path("frontend/nyx-pulse")
    for step in (["install"], ["run", "build"]):
        result = subprocess.run([npm, *step], cwd=str(front), shell=False)
        if result.returncode != 0:
            say(f"PROBLEM: `npm {' '.join(step)}` failed.")
            return False
    ok = ui_index().is_file()
    say("Workspace UI: built." if ok else "PROBLEM: the UI build produced no index.html.")
    return ok


# ---------------------------------------------------------------------------
# 4. Shortcuts
# ---------------------------------------------------------------------------


def _powershell(script: str, env: Dict[str, str]) -> subprocess.CompletedProcess:
    """Run an inline PowerShell command, passing values through the environment.

    Paths here contain spaces (the project lives in "Ai Dev Folder\\Ai Dev
    Folder"); passing them as environment variables avoids every quoting trap.
    Inline -Command is not subject to the script execution policy.
    """
    full_env = {**os.environ, **env}
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=60, env=full_env, creationflags=_CREATE_NO_WINDOW,
    )


def special_folder(name: str) -> Optional[Path]:
    """Desktop / Programs as Windows resolves them (handles OneDrive redirection)."""
    if sys.platform != "win32":
        return None
    result = _powershell(f"[Environment]::GetFolderPath('{name}')", {})
    value = (result.stdout or "").strip()
    return Path(value) if value else None


def shortcut_targets() -> List[Path]:
    targets: List[Path] = []
    desktop = special_folder("Desktop")
    if desktop is not None:
        targets.append(desktop / f"{SHORTCUT_NAME}.lnk")
    programs = special_folder("Programs")
    if programs is not None:
        targets.append(programs / f"{SHORTCUT_NAME}.lnk")
    return targets


def create_shortcut(location: Path) -> bool:
    """Write one .lnk that starts Nyx with no console window."""
    argv = launcher.launch_command()
    target, arguments = argv[0], launcher.command_line(argv[1:]) if len(argv) > 1 else ""
    icon = paths.project_path("assets/brand/nyx.ico")
    script = (
        "$shell = New-Object -ComObject WScript.Shell;"
        "$link = $shell.CreateShortcut($env:NYX_LNK);"
        "$link.TargetPath = $env:NYX_TARGET;"
        "$link.Arguments = $env:NYX_ARGS;"
        "$link.WorkingDirectory = $env:NYX_WORKDIR;"
        "$link.Description = 'Start Nyx Ichos, your local AI assistant';"
        "if ($env:NYX_ICON) { $link.IconLocation = $env:NYX_ICON };"
        "$link.Save()"
    )
    try:
        location.parent.mkdir(parents=True, exist_ok=True)
        result = _powershell(script, {
            "NYX_LNK": str(location),
            "NYX_TARGET": target,
            "NYX_ARGS": arguments,
            "NYX_WORKDIR": str(paths.PROJECT_DIR),
            "NYX_ICON": f"{icon},0" if icon.is_file() else "",
        })
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and location.is_file()


def remove_shortcuts() -> List[Path]:
    removed = []
    for location in shortcut_targets():
        try:
            if location.is_file():
                location.unlink()
                removed.append(location)
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def ready_marker() -> Path:
    return Path(sys.prefix) / READY_MARKER


def write_ready_marker() -> None:
    try:
        ready_marker().write_text(f"requirements={requirements_digest()}\n", encoding="utf-8")
    except OSError:
        pass


def install(autostart: bool = True, launch: bool = True, build_ui: bool = True) -> int:
    print()
    say("Nyx Ichos setup")
    say("-" * 44)

    if not ensure_packages():
        return 1
    if build_ui and not ensure_ui():
        return 1

    if sys.platform == "win32":
        say("Start link (nyx://): " + ("registered." if launcher.register_url_handler() else "could not register."))
        made = [str(p) for p in shortcut_targets() if create_shortcut(p)]
        if made:
            for path in made:
                say(f"Shortcut: {path}")
        else:
            say("Shortcuts: could not be created (Nyx still starts from Start Nyx.bat).")
        if autostart:
            say("Start with Windows: " + ("on." if launcher.set_autostart(True) else "could not be turned on."))
        else:
            say("Start with Windows: left as it was.")

    write_ready_marker()
    say("-" * 44)
    say("Done. From now on, double-click 'Nyx Ichos' on your desktop.")

    if launch:
        say("Starting Nyx...")
        launcher._spawn_detached(launcher.launch_command())
    print()
    return 0


def uninstall() -> int:
    say("Removing Nyx's shortcuts, nyx:// link and start-with-Windows entry.")
    say("Your chats, memory, keys and settings are left untouched.")
    for path in remove_shortcuts():
        say(f"Removed {path}")
    launcher.unregister_url_handler()
    launcher.set_autostart(False)
    try:
        ready_marker().unlink()
    except OSError:
        pass
    say("Done.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="setup_nyx", description="Make Nyx a one-click app on this PC.")
    parser.add_argument("--no-autostart", action="store_true", help="Do not start Nyx with Windows.")
    parser.add_argument("--no-launch", action="store_true", help="Set up, but do not start Nyx now.")
    parser.add_argument("--skip-ui", action="store_true", help="Do not check or build the web UI.")
    parser.add_argument("--uninstall", action="store_true", help="Remove shortcuts, the link and autostart.")
    args = parser.parse_args(argv)
    if args.uninstall:
        return uninstall()
    return install(autostart=not args.no_autostart, launch=not args.no_launch, build_ui=not args.skip_ui)


if __name__ == "__main__":
    raise SystemExit(main())
