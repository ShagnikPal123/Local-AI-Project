"""Regenerate AI_HANDOFF/API_ROUTES.md from the live FastAPI app.

Generated rather than hand-written so the route list another AI reads is never
stale: it is whatever `server.app` actually serves right now.

    .venv/Scripts/python.exe AI_HANDOFF/generate_routes.py
"""

from __future__ import annotations

import collections
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))
os.chdir(PROJECT)
# Import the app against a scratch data directory so generating docs never
# touches the owner's chats, memory or keys.
os.environ.setdefault("NYX_DATA_DIR", str(PROJECT / "local_pytest_tmp" / "handoff_data"))


def main() -> int:
    import server

    spec = server.app.openapi()
    groups: "collections.OrderedDict[str, list[str]]" = collections.OrderedDict()
    for path, operations in sorted(spec["paths"].items()):
        parts = path.split("/")
        section = parts[2] if path.startswith("/api/") and len(parts) > 2 else "other"
        for method, operation in operations.items():
            summary = (operation.get("description") or operation.get("summary") or "").strip()
            first = summary.split("\n")[0][:120]
            groups.setdefault(section, []).append(f"| `{method.upper()}` | `{path}` | {first} |")

    total = sum(len(rows) for rows in groups.values())
    lines = [
        "# API routes (generated)",
        "",
        "Regenerate: `.venv/Scripts/python.exe AI_HANDOFF/generate_routes.py`",
        "",
        f"{total} operations. Once an owner account exists every `/api/*` route needs a session, "
        "except `/api/health` and `/api/auth/*`.",
        "",
    ]
    router_status = getattr(server, "ROUTER_STATUS", {})
    if router_status:
        lines += ["Optional route modules: " + ", ".join(f"`{k}` {v}" for k, v in router_status.items()), ""]
    for section, rows in groups.items():
        lines += [f"## {section}", "", "| Method | Path | What it does |", "|---|---|---|", *rows, ""]
    (HERE / "API_ROUTES.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {total} operations to {HERE / 'API_ROUTES.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
