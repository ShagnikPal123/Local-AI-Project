# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the standalone Nyx build.

WARNING (2026-09-13): do not ship or point shortcuts at the resulting Nyx.exe
unless it is code-signed. Windows Smart App Control blocks unsigned executables
without reputation, and it silently refused this build on the owner's own PC
(CodeIntegrity event 3077). Users start Nyx through "Start Nyx.bat" and
launcher.py on Python's signed pythonw.exe instead; the download is built by
build_release.py.

Produces a folder (`dist/Nyx/`) containing `Nyx.exe`, a bundled CPython, every
dependency, and the built web UI. The user unzips it and double-clicks - no
Python install, no pip, no venv.

**One-dir, not one-file, deliberately.** A one-file build unpacks the whole
bundle to %TEMP% on every launch: slow, and it moves `sys._MEIPASS` around,
which breaks the project-relative path assumptions `paths.py` exists to
guarantee. One-dir starts fast and keeps paths stable.

Mutable state does NOT live here. `paths.py` routes it to %LOCALAPPDATA%/NyxIchos
whenever `sys.frozen` is set, because an installed app cannot write next to its
own executable.

Build with:  .venv/Scripts/python.exe -m PyInstaller nyx.spec --noconfirm
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

PROJECT = Path(SPECPATH)

# --- Data files -------------------------------------------------------------
# The built web UI is the product's entire interface; without it the server
# starts and serves nothing. `server.py` looks for frontend/nyx-pulse/dist, so
# the bundled layout has to match that relative shape exactly.
datas = [
    (str(PROJECT / "frontend" / "nyx-pulse" / "dist"), "frontend/nyx-pulse/dist"),
    (str(PROJECT / ".env.example"), "."),
    (str(PROJECT / "assets" / "brand"), "assets/brand"),
]

# Knowledge bases are read at runtime by knowledge.py, not imported, so
# PyInstaller cannot discover them by following imports.
for markdown in ("general_knowledge.md", "finance_knowledge.md"):
    source = PROJECT / markdown
    if source.is_file():
        datas.append((str(source), "."))

# --- Hidden imports ---------------------------------------------------------
# Providers and connectors are resolved dynamically through their registries,
# so a static import graph misses them and the app would ship with no way to
# reach a model.
hiddenimports = [
    *collect_submodules("providers"),
    *collect_submodules("connectors"),
    *collect_submodules("core"),
    # uvicorn selects its event loop, protocol and lifespan implementations by
    # string at runtime; none of them appear in the import graph.
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]

# Root-level modules that server.py imports lazily inside functions.
for module in (
    "chat_service", "router", "config", "paths", "auth", "server_auth",
    "memory", "chat_sessions", "skills", "widgets", "dynamic_tabs", "tab_editor",
    "overlay", "change_review", "machine_control", "resource_governor",
    "hardware_safety", "device_profile", "rag_memory", "knowledge", "storage",
    "personalities", "speech_patterns", "folder_reader", "secret_store",
    "event_log", "metrics", "deploy_mode", "health_check", "agent_team",
    "agent_pool", "fast_response", "tools", "web_access", "connectivity",
    "math_engine", "finance", "strands", "approaches", "attributes",
):
    if (PROJECT / f"{module}.py").is_file():
        hiddenimports.append(module)


a = Analysis(
    ["launcher.py"],
    pathex=[str(PROJECT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Excluded on purpose: these pull in tens of MB and nothing at runtime uses
    # them. numpy stays - math_engine and rag_memory rely on it.
    excludes=["tkinter", "matplotlib", "PIL", "pytest", "IPython", "notebook"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Nyx",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=True on purpose. This app's failure modes are "no API key" and
    # "port busy", and a windowed build would hide the message that explains
    # either one. The console is also where the engine's own log appears.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT / "assets" / "brand" / "nyx.ico")
    if (PROJECT / "assets" / "brand" / "nyx.ico").is_file()
    else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Nyx",
)
