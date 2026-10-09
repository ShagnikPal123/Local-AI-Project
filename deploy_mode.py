"""Build mode: local vs hosted (ROADMAP BB12).

A build that runs on Shagnik's own machine with full system access is **not the
same artefact** as one served to strangers on the open web. This module is the
single place that difference is decided.

In `hosted` mode the following are removed from the API entirely — not disabled,
not permission-gated, but absent, returning 404:

* **machine control** (files, desktop, browser, processes, apps) — an HTTP
  endpoint that reads a filesystem or takes screenshots, reachable from the
  internet, is a remote-access tool no matter how well it is gated.
* **admin edits to the base AI** — an agent that can rewrite its own code,
  exposed publicly, is remote code execution.
* **the overlay restore endpoint** — it can roll the whole install back.

A permission check protects against the *wrong user*. It does not protect
against a bug in the permission check itself. For the two capabilities above,
the safe design is that the code path does not exist in the hosted build, so
there is nothing to get wrong.

Set with `NYX_MODE=hosted` (or `local`, the default).
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any, Dict


class DeployMode(Enum):
    LOCAL = "local"    # the user's own machine; full capability
    HOSTED = "hosted"  # a public server; dangerous surfaces compiled out


def current_mode() -> DeployMode:
    """Read the mode, defaulting to local.

    Defaulting to *local* is deliberate: a misconfigured local install is
    inconvenient, while a hosted one that accidentally believes it is local is
    a breach. Deploying requires setting the variable explicitly, so the unsafe
    combination cannot happen by forgetting something.
    """
    raw = (os.getenv("NYX_MODE") or "").strip().lower()
    try:
        return DeployMode(raw) if raw else DeployMode.LOCAL
    except ValueError:
        return DeployMode.LOCAL


def is_hosted() -> bool:
    return current_mode() is DeployMode.HOSTED


# Route prefixes removed from a hosted build.
HOSTED_BLOCKED_PREFIXES = (
    "/api/machine",
    # Reading and editing files on the host (Code tab, VS Code extension).
    "/api/code",
    # Brokerage keys and orders live only on the owner's own machine.
    "/api/trading",
    # Request R: studying fetched pages into this machine's memory, watching and driving its screen, Nyx editing its
    # own code, the unrestricted Free Will chat, and scanning the disk for model files all belong to the owner's PC.
    "/api/absorb",
    "/api/data-process",
    "/api/screen",
    "/api/apply",
    "/api/freewill",
    "/api/local-models",
    # Request S: Big Kahuna sees every answer and opens things on this PC by voice.
    "/api/identity0",
    # Project Null N8: an office of agents runs on the owner's own keys, writes into their own folders and can
    # pause the rest of Nyx. None of that belongs to a hosted visitor.
    "/api/office",
    # UPDATE_IDEAS U34–U40: a world is an office that runs for days on the owner's keys. Not for a hosted visitor.
    "/api/world",
    # The owner's WhatsApp line reaches their own phone and is tied to their own PC.
    "/api/whatsapp",
    # Project Null N92/N103/N104: the always-listening microphone that acts on this PC, Nyx's own
    # questions and mistakes, and the money it is allowed to work with.
    "/api/proto-voice",
    "/api/curiosity",
    "/api/finance-lab",
    "/api/overlay/restore",
    # Accounts split one PC's data into folders and restart the engine; a hosted build has real sign-in instead.
    "/api/accounts",
    # First-run ownership claim. On a hosted deployment "whoever asks first
    # becomes the owner" is a land-grab, so the route simply does not exist
    # there; a hosted install is provisioned deliberately, not claimed.
    "/api/auth/claim",
)


def is_route_available(path: str) -> bool:
    """Whether a route exists in the current mode."""
    if not is_hosted():
        return True
    return not any(path.startswith(prefix) for prefix in HOSTED_BLOCKED_PREFIXES)


def hosted_blocked_reason(path: str) -> str:
    if path.startswith("/api/machine"):
        return (
            "Machine control is not available in the hosted build. It exists only "
            "in the local/desktop version, where it runs on your own machine."
        )
    return (
        "This capability is not available in the hosted build. Use the "
        "local/desktop version."
    )


def describe() -> Dict[str, Any]:
    """What this build is and is not, for the UI and for `/api/health`."""
    hosted = is_hosted()
    return {
        "mode": current_mode().value,
        "machine_control": not hosted,
        "base_ai_edits": not hosted,
        "overlay_restore": not hosted,
        "note": (
            "Hosted build: machine control and base-AI edits are compiled out, "
            "not merely disabled."
            if hosted else
            "Local build: full capability, running on this machine."
        ),
    }
