"""Utility script to install and start Ollama locally for Nyx Pulse."""

from __future__ import annotations

import os
import subprocess
import time

OLLAMA_EXE = r"C:\Users\shagn\AppData\Local\Programs\Ollama\ollama.exe"
DEFAULT_MODEL = "llama3.2"

#: Ollama and winget are console programs: without this they open a black window
#: in front of whatever the owner is doing (Plan Null N87).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ensure_ollama_installed() -> str:
    if os.path.exists(OLLAMA_EXE):
        return OLLAMA_EXE

    install = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "winget install --id Ollama.Ollama --accept-source-agreements --accept-package-agreements --silent",
        ],
        capture_output=True,
        text=True,
        creationflags=_NO_WINDOW,
    )
    if install.returncode == 0 and os.path.exists(OLLAMA_EXE):
        return OLLAMA_EXE
    raise RuntimeError("Ollama is not installed and could not be installed automatically.")


def ensure_server_running() -> subprocess.Popen:
    exe = ensure_ollama_installed()
    server = subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              creationflags=_NO_WINDOW)
    time.sleep(8)
    return server


def ensure_model(model: str = DEFAULT_MODEL) -> str:
    exe = ensure_ollama_installed()
    list_result = subprocess.run([exe, "list"], capture_output=True, text=True, creationflags=_NO_WINDOW)
    if model not in (list_result.stdout or ""):
        pull = subprocess.run([exe, "pull", model], capture_output=True, text=True, timeout=600,
                              creationflags=_NO_WINDOW)
        if pull.returncode != 0:
            raise RuntimeError(f"Failed to pull model '{model}': {pull.stderr or pull.stdout}")
    return model


def main() -> None:
    ensure_server_running()
    model = ensure_model()
    print(f"Ollama ready. Model: {model}")


if __name__ == "__main__":
    main()
