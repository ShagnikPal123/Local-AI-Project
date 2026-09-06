"""User-defined tabs (ROADMAP CC1-CC12).

Tabs stop being a fixed set. The user asks for one — "I want a notes tab", "make
me somewhere for my email" — and the agent builds it. Each install diverges from
the shipped app without forking it.

**A tab is a declarative spec, never generated code.** A spec names blocks the
client already knows how to render, plus which connectors it may call. The app
interprets it; nothing here is executed. Free-form codegen into a running client
would be an XSS and RCE surface, and it would break the update path in AA10-AA11
because an update could not reason about arbitrary user code.

The same reasoning gave widgets, skills, and the overlay their shapes. This is
the largest surface of the four, so it matters most here.
"""

from __future__ import annotations

import json
import re
import time
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set
from paths import data_path

_WORD_RE = re.compile(r"[a-z][a-z0-9]{1,}")


class BlockType(Enum):
    """Blocks the client can render. A spec may only use these."""

    TEXT = "text"            # static prose
    NOTES = "notes"          # editable notes, stored locally
    CHECKLIST = "checklist"  # tickable items
    CHAT = "chat"            # a scoped conversation
    LIST = "list"            # items from a connector
    STAT = "stat"            # a single reading
    LINKS = "links"          # a set of links
    EMBED = "embed"          # another tab, rendered inline


class TabSpecError(Exception):
    """Raised when a tab spec is malformed or unsafe."""


# Connectors a generated tab may reference. Anything outside this cannot be
# named by a spec at all — a tab the agent wrote for a user must not be able to
# reach machine control by asking for it.
ALLOWED_CONNECTORS = frozenset({
    "web_search", "youtube", "finance", "local_files", "google",
})

_MAX_BLOCKS = 12
_ICON_RE = re.compile(r"^ph-[a-z0-9-]{2,40}$")


@dataclass
class Block:
    type: BlockType
    title: str = ""
    config: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {"type": self.type.value, "title": self.title, "config": dict(self.config)}


#: Kept per tab. Long enough to show what you changed recently, short enough
#: that tabs.json cannot grow without bound.
_MAX_EDITS = 20


@dataclass
class TabEdit:
    """One applied change to a tab, kept so the UI can prove it happened.

    A tab used to record nothing about its own history, so after an edit there
    was no way for the interface to show what had been asked for or whether it
    landed - the change either appeared or it did not, with no explanation
    either way. Storing the request alongside the resulting summary lets the
    panel display "you asked X, this changed Y" and keep showing it.
    """

    request: str        # what the user actually typed
    summary: str        # what changed, in plain words
    at: float           # unix seconds
    source: str = "local"   # local (deterministic) | model

    def as_dict(self) -> Dict[str, Any]:
        return {"request": self.request, "summary": self.summary,
                "at": self.at, "source": self.source}


@dataclass
class TabSpec:
    tab_id: str
    label: str
    icon: str = "ph-squares-four"
    description: str = ""
    blocks: List[Block] = field(default_factory=list)
    connectors: List[str] = field(default_factory=list)
    accent: str = ""
    author: str = ""
    source: str = "user"      # user | agent | derived
    # Set when this tab overrides a shipped one, so it can be reset (CC12).
    overrides: str = ""
    edits: List["TabEdit"] = field(default_factory=list)
    updated_at: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.tab_id,
            "label": self.label,
            "icon": self.icon,
            "description": self.description,
            "blocks": [b.as_dict() for b in self.blocks],
            "connectors": list(self.connectors),
            "accent": self.accent,
            "author": self.author,
            "source": self.source,
            "overrides": self.overrides,
            "edits": [e.as_dict() for e in self.edits],
            "updated_at": self.updated_at,
        }

    def search_terms(self) -> Set[str]:
        text = f"{self.label} {self.description} " + " ".join(
            b.title for b in self.blocks
        )
        return set(_WORD_RE.findall(text.lower()))



def _describe_changes(before: "TabSpec", after: "TabSpec") -> str:
    """Summarise what actually changed, in words a person would use.

    Reports the resulting state rather than the request, so an edit that was
    understood but had no effect ("make it green" when it is already green)
    reads as no change instead of as success.
    """
    parts: List[str] = []
    if before.label != after.label:
        parts.append(f"renamed to “{after.label}”")
    if before.accent != after.accent:
        parts.append(f"colour set to {after.accent}" if after.accent else "colour cleared")
    if before.icon != after.icon:
        parts.append(f"icon changed to {after.icon}")
    if before.description != after.description:
        parts.append("description updated")

    old_titles = [b.title for b in before.blocks]
    new_titles = [b.title for b in after.blocks]
    if old_titles != new_titles:
        added = [x for x in new_titles if x not in old_titles]
        removed = [x for x in old_titles if x not in new_titles]
        for title in added:
            parts.append(f"added the “{title}” block")
        for title in removed:
            parts.append(f"removed the “{title}” block")
        if not added and not removed:
            parts.append("reordered the blocks")

    if sorted(before.connectors) != sorted(after.connectors):
        parts.append("connectors updated")

    return "; ".join(parts)


def _validate_icon(icon: str) -> str:
    """Icons are Phosphor names. Anything else could inject markup."""
    clean = (icon or "").strip() or "ph-squares-four"
    if not _ICON_RE.match(clean):
        raise TabSpecError(f"Invalid icon {clean!r}: expected a Phosphor name like ph-note.")
    return clean


def _validate_accent(accent: str) -> str:
    """Accent is a hex colour or a design token, never arbitrary CSS."""
    clean = (accent or "").strip()
    if not clean:
        return ""
    if re.match(r"^#[0-9a-fA-F]{6}$", clean):
        return clean
    if re.match(r"^var\(--color-[a-z0-9-]{2,40}\)$", clean):
        return clean
    raise TabSpecError(
        f"Invalid accent {clean!r}: use a #rrggbb colour or a var(--color-…) token."
    )


def _validate_connectors(connectors: Sequence[str]) -> List[str]:
    cleaned = []
    for name in connectors or []:
        clean = str(name).strip().lower()
        if not clean:
            continue
        if clean not in ALLOWED_CONNECTORS:
            raise TabSpecError(
                f"Connector {clean!r} cannot be used by a generated tab. "
                f"Allowed: {', '.join(sorted(ALLOWED_CONNECTORS))}."
            )
        if clean not in cleaned:
            cleaned.append(clean)
    return cleaned


def build_spec(
    label: str,
    blocks: Sequence[Dict[str, Any]],
    icon: str = "ph-squares-four",
    description: str = "",
    connectors: Sequence[str] = (),
    accent: str = "",
    author: str = "",
    source: str = "user",
    tab_id: Optional[str] = None,
) -> TabSpec:
    """Validate raw input into a TabSpec, or raise.

    Every field is checked here rather than at render time, so an invalid spec
    can never be stored and then fail in front of the user.
    """
    clean_label = (label or "").strip()
    if not clean_label:
        raise TabSpecError("A tab needs a name.")
    if len(clean_label) > 40:
        raise TabSpecError("That tab name is too long for the nav.")

    if not blocks:
        raise TabSpecError("A tab needs at least one block, or there is nothing to show.")
    if len(blocks) > _MAX_BLOCKS:
        raise TabSpecError(f"A tab can have at most {_MAX_BLOCKS} blocks.")

    parsed: List[Block] = []
    for raw in blocks:
        try:
            block_type = BlockType(str(raw.get("type", "")).strip().lower())
        except ValueError as error:
            raise TabSpecError(
                f"Unknown block type {raw.get('type')!r}. Available: "
                f"{', '.join(b.value for b in BlockType)}."
            ) from error
        parsed.append(Block(
            type=block_type,
            title=str(raw.get("title", "")).strip()[:60],
            config={k: v for k, v in (raw.get("config") or {}).items()
                    if isinstance(k, str)},
        ))

    return TabSpec(
        tab_id=tab_id or f"user-{uuid.uuid4().hex[:8]}",
        label=clean_label,
        icon=_validate_icon(icon),
        description=(description or "").strip()[:200],
        blocks=parsed,
        connectors=_validate_connectors(connectors),
        accent=_validate_accent(accent),
        author=author,
        source=source,
    )


class TabStore:
    """Per-user tab definitions, persisted separately from the shipped app."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else data_path("tabs.json")
        self._tabs: Dict[str, TabSpec] = {}
        self._lock = threading.Lock()
        self._load()

    # --- persistence --------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        for entry in raw.get("tabs", []):
            try:
                spec = build_spec(
                    label=entry["label"],
                    blocks=entry.get("blocks", []),
                    icon=entry.get("icon", "ph-squares-four"),
                    description=entry.get("description", ""),
                    connectors=entry.get("connectors", []),
                    accent=entry.get("accent", ""),
                    author=entry.get("author", ""),
                    source=entry.get("source", "user"),
                    tab_id=entry.get("id"),
                )
                spec.overrides = str(entry.get("overrides", ""))
            except Exception:
                # Skip an invalid stored tab rather than losing the rest. Also
                # means a spec that was valid under older rules and is not now
                # simply disappears instead of breaking the nav.
                continue
            self._tabs[spec.tab_id] = spec

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"tabs": [t.as_dict() for t in self._tabs.values()]}
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    # --- reads --------------------------------------------------------------

    def list_tabs(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [t.as_dict() for t in sorted(self._tabs.values(), key=lambda t: t.label)]

    def get(self, tab_id: str) -> Optional[TabSpec]:
        with self._lock:
            return self._tabs.get(tab_id)

    def find(self, query: str, shipped: Sequence[Dict[str, str]] = ()) -> List[Dict[str, Any]]:
        """Fuzzy tab search (CC2).

        The user types what they call it, not what it is called. "my email thing"
        should find a Mail tab. Matches on label, description, and block titles,
        and reports why each result matched so a wrong guess is obvious.
        """
        terms = set(_WORD_RE.findall((query or "").lower()))
        if not terms:
            return []

        results: List[Dict[str, Any]] = []

        for entry in shipped:
            label = str(entry.get("label", ""))
            candidate = set(_WORD_RE.findall(f"{label} {entry.get('id', '')}".lower()))
            shared = terms & candidate
            if shared:
                results.append({
                    "id": entry.get("id", ""),
                    "label": label,
                    "source": "shipped",
                    "score": len(shared),
                    "matched": sorted(shared),
                })

        with self._lock:
            for spec in self._tabs.values():
                shared = terms & spec.search_terms()
                if shared:
                    results.append({
                        "id": spec.tab_id,
                        "label": spec.label,
                        "source": spec.source,
                        "score": len(shared),
                        "matched": sorted(shared),
                    })

        results.sort(key=lambda r: (-r["score"], r["label"]))
        return results

    # --- writes -------------------------------------------------------------

    def create(self, spec: TabSpec) -> TabSpec:
        with self._lock:
            self._tabs[spec.tab_id] = spec
            self._save()
            return spec

    def update(
        self,
        tab_id: str,
        request: str = "",
        edit_source: str = "local",
        **changes: Any,
    ) -> TabSpec:
        """Edit an existing tab (CC9, CC10). Every field is re-validated.

        ``request`` is what the user typed. It is recorded alongside a summary of
        what actually changed, because an edit that silently succeeds is
        indistinguishable from one that silently failed - which is exactly how
        this felt to use.
        """
        with self._lock:
            existing = self._tabs.get(tab_id)
            if existing is None:
                raise TabSpecError("No such tab.")

            merged = existing.as_dict()
            merged.update({k: v for k, v in changes.items() if v is not None})

            spec = build_spec(
                label=merged["label"],
                blocks=merged["blocks"],
                icon=merged["icon"],
                description=merged["description"],
                connectors=merged["connectors"],
                accent=merged["accent"],
                author=existing.author,
                source=existing.source,
                tab_id=tab_id,
            )
            spec.overrides = existing.overrides

            # Compare against what was there before, not against the request, so
            # the summary reports what the tab actually became. Asking for green
            # and getting nothing must not read as success.
            summary = _describe_changes(existing, spec)
            spec.edits = list(existing.edits)
            if summary:
                spec.edits.append(
                    TabEdit(
                        request=(request or "").strip()[:200],
                        summary=summary,
                        at=time.time(),
                        source=edit_source,
                    )
                )
                spec.edits = spec.edits[-_MAX_EDITS:]
                spec.updated_at = time.time()
            else:
                spec.updated_at = existing.updated_at

            self._tabs[tab_id] = spec
            self._save()
            return spec

    def combine(self, first_id: str, second_id: str, label: str = "") -> TabSpec:
        """Merge two tabs into one (CC11). The originals are left alone."""
        with self._lock:
            left = self._tabs.get(first_id)
            right = self._tabs.get(second_id)
        if left is None or right is None:
            raise TabSpecError("Both tabs must exist to combine them.")

        blocks = [b.as_dict() for b in left.blocks] + [b.as_dict() for b in right.blocks]
        if len(blocks) > _MAX_BLOCKS:
            raise TabSpecError(
                f"Combining these would make {len(blocks)} blocks, over the limit of "
                f"{_MAX_BLOCKS}. Remove some blocks first."
            )

        spec = build_spec(
            label=label.strip() or f"{left.label} + {right.label}",
            blocks=blocks,
            icon=left.icon,
            description=f"Combined from {left.label} and {right.label}.",
            connectors=list(dict.fromkeys(left.connectors + right.connectors)),
            accent=left.accent,
            source="derived",
        )
        return self.create(spec)

    def delete(self, tab_id: str) -> bool:
        with self._lock:
            if tab_id not in self._tabs:
                return False
            del self._tabs[tab_id]
            self._save()
            return True


def build_tab_prompt(description: str) -> str:
    """Prompt asking a model to design a tab from a description (CC4, CC5)."""
    return (
        "Design a tab for a personal AI assistant from this request:\n\n"
        f"{description}\n\n"
        "Reply with JSON only, no prose, in exactly this shape:\n"
        '{"label": "...", "icon": "ph-...", "description": "...", '
        '"blocks": [{"type": "...", "title": "..."}], "connectors": []}\n\n'
        f"Block types available: {', '.join(b.value for b in BlockType)}.\n"
        f"Connectors available: {', '.join(sorted(ALLOWED_CONNECTORS))} (use only if needed).\n"
        "Icons are Phosphor names, e.g. ph-note, ph-envelope, ph-chart-line.\n"
        "Use between one and six blocks. Choose the blocks that actually serve the "
        "request rather than filling space."
    )


def parse_tab_reply(reply: str) -> Dict[str, Any]:
    """Parse a model reply produced by `build_tab_prompt`.

    Tolerates a fenced code block, since models often wrap JSON. Raises rather
    than returning something partial — a malformed tab would render broken.
    """
    text = (reply or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]

    try:
        data = json.loads(text)
    except Exception as error:
        raise TabSpecError("The model did not return usable JSON for the tab.") from error
    if not isinstance(data, dict) or not data.get("label") or not data.get("blocks"):
        raise TabSpecError("The model reply was missing a label or blocks.")
    return data


TAB_STORE = TabStore()
