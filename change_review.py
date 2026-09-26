r"""Change proposal, review, and publication (ROADMAP AA7-AA11, F7).

The pipeline behind the Admin Changes tab: every modification to the app —
whether Shagnik made it by hand, or the agent proposed it for itself — becomes a
reviewable record before it can reach anyone else.

    draft -> in_review -> approved -> published
                       \-> rejected
    published -> rolled_back

Three rules shape this:

1. **Nothing publishes without passing through review.** A change cannot jump
   from draft to published, including one the agent wrote itself. This is the
   gate that makes agent self-modification safe to leave switched on.
2. **Publishing is an outward-facing act.** It changes the app for every user
   who accepts the update, so it needs `PUBLISH_CHANGES` and is recorded with
   who did it and when.
3. **Everything is reversible.** A published change keeps its original content so
   a rollback restores the prior state rather than guessing at it.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from paths import data_path


class ChangeStatus(Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


class ChangeOrigin(Enum):
    """Who proposed it. Agent-authored changes are held to the same gate."""

    HUMAN = "human"
    AGENT = "agent"


# Which transitions are legal. Anything absent is refused, so a new status cannot
# accidentally become publishable by omission.
_ALLOWED: Dict[ChangeStatus, frozenset[ChangeStatus]] = {
    ChangeStatus.DRAFT: frozenset({ChangeStatus.IN_REVIEW, ChangeStatus.REJECTED}),
    ChangeStatus.IN_REVIEW: frozenset({ChangeStatus.APPROVED, ChangeStatus.REJECTED}),
    ChangeStatus.APPROVED: frozenset({ChangeStatus.PUBLISHED, ChangeStatus.REJECTED}),
    ChangeStatus.PUBLISHED: frozenset({ChangeStatus.ROLLED_BACK}),
    ChangeStatus.REJECTED: frozenset(),
    ChangeStatus.ROLLED_BACK: frozenset(),
}


class ChangeError(Exception):
    """Raised for an illegal transition or a malformed change."""


@dataclass
class Change:
    change_id: str
    title: str
    description: str
    author: str
    origin: ChangeOrigin
    # Which surface this touches: a tab id, a module path, or "base_ai".
    target: str
    # What it does. Kept as text so the record is readable without the app.
    content: str = ""
    # The state before this change, so a rollback restores rather than guesses.
    previous_content: str = ""
    status: ChangeStatus = ChangeStatus.DRAFT
    ai_review: str = ""
    reviewed_by: str = ""
    published_by: str = ""
    created_at: float = field(default_factory=time.time)
    published_at: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.change_id,
            "title": self.title,
            "description": self.description,
            "author": self.author,
            "origin": self.origin.value,
            "target": self.target,
            "content": self.content,
            "previous_content": self.previous_content,
            "status": self.status.value,
            "ai_review": self.ai_review,
            "reviewed_by": self.reviewed_by,
            "published_by": self.published_by,
            "created_at": self.created_at,
            "published_at": self.published_at,
            "can_publish": self.status is ChangeStatus.APPROVED,
        }


class ChangeLog:
    """File-backed record of every proposed and published change."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else data_path("changes.json")
        self._changes: Dict[str, Change] = {}
        self._lock = threading.Lock()
        self._load()

    # --- persistence --------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        for entry in raw.get("changes", []):
            try:
                change = Change(
                    change_id=str(entry["id"]),
                    title=str(entry.get("title", "")),
                    description=str(entry.get("description", "")),
                    author=str(entry.get("author", "")),
                    origin=ChangeOrigin(entry.get("origin", "human")),
                    target=str(entry.get("target", "")),
                    content=str(entry.get("content", "")),
                    previous_content=str(entry.get("previous_content", "")),
                    status=ChangeStatus(entry.get("status", "draft")),
                    ai_review=str(entry.get("ai_review", "")),
                    reviewed_by=str(entry.get("reviewed_by", "")),
                    published_by=str(entry.get("published_by", "")),
                    created_at=float(entry.get("created_at", time.time())),
                    published_at=entry.get("published_at"),
                )
            except Exception:
                # Skip an unreadable record rather than losing the whole history.
                continue
            self._changes[change.change_id] = change

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"changes": [c.as_dict() for c in self._ordered()]}
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _ordered(self) -> List[Change]:
        return sorted(self._changes.values(), key=lambda c: c.created_at, reverse=True)

    # --- reads --------------------------------------------------------------

    def list_changes(self, status: Optional[ChangeStatus] = None) -> List[Dict[str, Any]]:
        with self._lock:
            changes = self._ordered()
        if status is not None:
            changes = [c for c in changes if c.status is status]
        return [c.as_dict() for c in changes]

    def get(self, change_id: str) -> Optional[Change]:
        with self._lock:
            return self._changes.get(change_id)

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            changes = list(self._changes.values())
        counts = {s.value: 0 for s in ChangeStatus}
        for change in changes:
            counts[change.status.value] += 1
        return {
            "total": len(changes),
            "counts": counts,
            "awaiting_review": counts[ChangeStatus.IN_REVIEW.value],
            "ready_to_publish": counts[ChangeStatus.APPROVED.value],
        }

    # --- writes -------------------------------------------------------------

    def propose(
        self,
        title: str,
        description: str,
        author: str,
        target: str,
        content: str = "",
        previous_content: str = "",
        origin: ChangeOrigin = ChangeOrigin.HUMAN,
    ) -> Change:
        """Record a proposed change. Always starts as a draft."""
        if not title.strip():
            raise ChangeError("A change needs a title.")

        # Validate the target here, where it is written, rather than letting a
        # bad one sit in the review queue looking approvable and only failing
        # when somebody tries to publish it.
        try:
            from overlay import OverlayError, validate_target

            target = validate_target(target)
        except ImportError:  # pragma: no cover - overlay is always present
            if not target.strip():
                raise ChangeError("A change needs a target.")
            target = target.strip()
        except OverlayError as error:
            raise ChangeError(str(error)) from error

        change = Change(
            change_id=uuid.uuid4().hex[:10],
            title=title.strip(),
            description=description.strip(),
            author=author,
            origin=origin,
            target=target.strip(),
            content=content,
            previous_content=previous_content,
        )
        with self._lock:
            self._changes[change.change_id] = change
            self._save()
        return change

    def record_content(self, change_id: str, content: str, previous_content: str) -> Change:
        """Attach what a change actually did (a diff) and what it replaced.

        Used when an approved proposal is implemented: the record then holds the
        real edit instead of a description of one, and rollback has the prior text.
        """
        with self._lock:
            change = self._changes.get(change_id)
            if change is None:
                raise ChangeError("No such change.")
            change.content = content
            change.previous_content = previous_content
            self._save()
            return change

    def _transition(self, change_id: str, to: ChangeStatus) -> Change:
        """Move a change to a new status, refusing anything not in the table."""
        with self._lock:
            change = self._changes.get(change_id)
            if change is None:
                raise ChangeError("No such change.")
            if to not in _ALLOWED.get(change.status, frozenset()):
                raise ChangeError(
                    f"Cannot go from {change.status.value} to {to.value}."
                )
            change.status = to
            self._save()
            return change

    def submit_for_review(self, change_id: str) -> Change:
        return self._transition(change_id, ChangeStatus.IN_REVIEW)

    def attach_review(self, change_id: str, review: str, reviewer: str) -> Change:
        """Record a review without deciding the outcome.

        Deliberately separate from approval: reading a review and accepting it
        are different acts, and collapsing them would let an AI review approve
        its own change.
        """
        with self._lock:
            change = self._changes.get(change_id)
            if change is None:
                raise ChangeError("No such change.")
            change.ai_review = review
            change.reviewed_by = reviewer
            self._save()
            return change

    def approve(self, change_id: str, reviewer: str) -> Change:
        change = self._transition(change_id, ChangeStatus.APPROVED)
        with self._lock:
            change.reviewed_by = reviewer
            self._save()
        return change

    def reject(self, change_id: str, reviewer: str, reason: str = "") -> Change:
        change = self._transition(change_id, ChangeStatus.REJECTED)
        with self._lock:
            change.reviewed_by = reviewer
            if reason:
                change.ai_review = (change.ai_review + f"\nRejected: {reason}").strip()
            self._save()
        return change

    def publish(self, change_id: str, publisher: str) -> Change:
        """Publish an approved change. Records who and when."""
        change = self._transition(change_id, ChangeStatus.PUBLISHED)
        with self._lock:
            change.published_by = publisher
            change.published_at = time.time()
            self._save()
        return change

    def rollback(self, change_id: str, actor: str) -> Change:
        """Revert a published change back to its previous content."""
        change = self._transition(change_id, ChangeStatus.ROLLED_BACK)
        with self._lock:
            change.content = change.previous_content
            change.published_by = actor
            self._save()
        return change


CHANGE_LOG = ChangeLog()


def build_review_prompt(change: Change) -> str:
    """The prompt used to ask a model to review a change.

    Asks for problems rather than a verdict. A reviewer prompted to approve will
    approve, which would defeat the purpose of having a review step at all.
    """
    return (
        "You are reviewing a proposed change to a local-first AI assistant before "
        "it is published to users.\n\n"
        f"Title: {change.title}\n"
        f"Target: {change.target}\n"
        f"Proposed by: {change.author} ({change.origin.value})\n"
        f"Description: {change.description}\n\n"
        f"--- proposed content ---\n{change.content[:4000]}\n\n"
        "Identify concrete problems: correctness bugs, security issues, anything "
        "that could break existing users, and anything the description claims but "
        "the content does not do. If you find nothing wrong, say so plainly and "
        "briefly. Do not approve or reject — a person decides that."
    )
