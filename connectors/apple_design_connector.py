"""Apple Design & HIG Connector — inspect and read 122 Apple Human Interface Guidelines.

Enables Nyx to look up design principles, component specs, accessibility requirements,
materials (Liquid Glass), typography, layout, and mobile/desktop platform conventions.
Based on https://github.com/dickwu/apple-design-skill.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from connectors.base import BaseConnector, ConnectorManifest
from paths import project_path


class AppleDesignConnector(BaseConnector):
    """Local, offline access to Apple's Human Interface Guidelines (HIG)."""

    def __init__(self, root_dir: Optional[Path] = None) -> None:
        if root_dir is None:
            self.root = project_path("skills/apple-design/references")
        else:
            self.root = Path(root_dir)
        self.hig_dir = self.root / "hig"
        self.lookup_file = self.root / "hig-lookup.md"

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            name="apple_design",
            description=(
                "Access Apple's Human Interface Guidelines (122 HIG reference files). "
                "Search design patterns, look up component guidelines, accessibility rules, "
                "and Liquid Glass styling specifications."
            ),
            permissions=["read"],
            is_offline=True,
            requires_auth=False,
            is_write=False,
            risk_level="low",
            config_schema={
                "action": {
                    "type": "string",
                    "enum": ["lookup", "read", "list_topics"],
                    "description": "Action to perform: lookup (search), read (get guideline), list_topics (categories).",
                },
                "query": {"type": "string", "description": "Search term or topic name."},
            },
        )

    def is_available(self) -> bool:
        """Returns True if the HIG references are installed on disk."""
        return self.hig_dir.is_dir() and any(self.hig_dir.iterdir())

    def lookup(self, query: str = "") -> List[Dict[str, str]]:
        """Search the HIG routing table for matching guideline topics."""
        if not self.lookup_file.is_file():
            return []
        
        q = (query or "").strip().lower()
        results: List[Dict[str, str]] = []
        try:
            content = self.lookup_file.read_text(encoding="utf-8")
        except OSError:
            return []

        for line in content.splitlines():
            line_clean = line.strip()
            if not line_clean.startswith("|") or "---" in line_clean:
                continue
            parts = [p.strip() for p in line_clean.split("|")[1:-1]]
            if len(parts) >= 2 and parts[0] != "Guideline":
                topic = parts[0]
                # Columns are Guideline | File | Covers | Apple last changed. The
                # summary is "Covers" — column 1 is only the filename again.
                summary = parts[2] if len(parts) >= 3 else parts[1]
                haystack = f"{topic} {summary}".lower()
                words = [w for w in re.split(r"\W+", q) if len(w) > 2]
                # Rank by how many query words a topic mentions (title hits count
                # double), so "glass blur materials" finds Materials and Liquid
                # Glass instead of nothing.
                title_text = topic.lower()
                score = (100 if q and q in haystack else 0) + sum(
                    (2 if w in title_text else 1) for w in words if w in haystack
                )
                if not q or score > 0:
                    file_match = re.search(r"\[([^\]]+)\]\(([^)]+)\)", topic)
                    title = file_match.group(1) if file_match else topic.replace("`", "")
                    filename = file_match.group(2) if file_match else f"{title.lower().replace(' ', '-')}.md"
                    results.append({
                        "topic": title,
                        "summary": summary,
                        "file": filename,
                        "score": score,
                    })
        results.sort(key=lambda item: -item["score"])
        return results[:20]

    def read_guideline(self, topic_or_file: str) -> Dict[str, Any]:
        """Read a specific HIG guideline markdown document."""
        if not self.is_available():
            return {"ok": False, "error": "Apple Design HIG library is not available on disk."}

        target = (topic_or_file or "").strip()
        if not target.endswith(".md"):
            # Try to match by slug or exact name
            slug = re.sub(r"[^a-z0-9]+", "-", target.lower()).strip("-")
            candidate = self.hig_dir / f"{slug}.md"
            if not candidate.exists():
                # Check for partial match among files
                for f in self.hig_dir.glob("*.md"):
                    if slug in f.stem.lower():
                        candidate = f
                        break
        else:
            candidate = self.hig_dir / Path(target).name

        if not candidate.exists():
            return {
                "ok": False,
                "error": f"Guideline '{topic_or_file}' not found. Try apple_design_lookup to find matching topics.",
            }

        try:
            text = candidate.read_text(encoding="utf-8")
            return {
                "ok": True,
                "file": candidate.name,
                "topic": candidate.stem.replace("-", " ").title(),
                "content": text,
            }
        except OSError as err:
            return {"ok": False, "error": f"Could not read guideline: {err}"}

    def list_topics(self) -> List[str]:
        """List all available HIG guideline topics."""
        if not self.hig_dir.is_dir():
            return []
        return sorted([f.stem.replace("-", " ") for f in self.hig_dir.glob("*.md")])

    def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Execute a connector action."""
        act = (action or "").strip().lower()
        if act == "lookup":
            query = str(params.get("query", "") or "")
            results = self.lookup(query)
            return {"ok": True, "query": query, "count": len(results), "matches": results}
        elif act in ("read", "read_guideline"):
            topic = str(params.get("topic", "") or params.get("query", "") or "")
            return self.read_guideline(topic)
        elif act == "list_topics":
            topics = self.list_topics()
            return {"ok": True, "count": len(topics), "topics": topics}
        else:
            return {"ok": False, "error": f"Unknown action '{action}'. Valid actions: lookup, read, list_topics."}
