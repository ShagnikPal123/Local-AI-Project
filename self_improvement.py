'''Approval-gated continuous improvement primitives.'''
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, List


@dataclass
class ImprovementProposal:
    proposal_id: str
    kind: str
    description: str
    candidate: dict[str, Any]
    status: str = "beta"
    created_at: str = ""


class ImprovementStore:
    def __init__(self, path: str = "training/proposals.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _write(self, proposals: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(proposals, indent=2), encoding="utf-8")

    def propose(self, kind: str, description: str, candidate: dict[str, Any]) -> ImprovementProposal:
        proposals = self._read()
        proposal = ImprovementProposal(f"proposal-{len(proposals) + 1}", kind, description, candidate, created_at=datetime.now(timezone.utc).isoformat())
        proposals.append(asdict(proposal))
        self._write(proposals)
        return proposal

    def promote(self, proposal_id: str, owner_approved: bool) -> ImprovementProposal:
        if not owner_approved:
            raise PermissionError("Explicit owner approval is required before promotion.")
        proposals = self._read()
        for item in proposals:
            if item.get("proposal_id") == proposal_id:
                item["status"] = "live"
                self._write(proposals)
                return ImprovementProposal(**item)
        raise KeyError(f"Unknown proposal: {proposal_id}")

    def list(self) -> list[dict[str, Any]]:
        """Return all proposals (newest first)."""
        return list(reversed(self._read()))

    def summary(self) -> str:
        """Human-readable proposal list for the CLI."""
        proposals = self.list()
        if not proposals:
            return "No improvement proposals yet. Run /improve scan to discover ideas online."
        lines = [f"Improvement proposals ({len(proposals)}):"]
        for item in proposals:
            lines.append(
                f"  {item['proposal_id']} [{item['status']}] ({item['kind']}) "
                f"{item['description']} — created {item['created_at'][:10]}"
            )
        return "\n".join(lines)


def scan_online_improvements(topic: str = "python ai assistant", limit: int = 3) -> List[ImprovementProposal]:
    """Scan the web for new features and known issues, then file approval-gated proposals.

    Never modifies code: every discovery is stored as a 'beta' proposal that
    requires explicit owner approval (promote) before it can go live.

    Returns [] when offline or when nothing relevant is found.
    """
    try:
        from connectivity import is_online
        from web_access import answer

        if not is_online():
            return []
    except Exception:
        return []

    store = ImprovementStore()
    created: List[ImprovementProposal] = []
    queries = [
        f"latest features and best practices for {topic} 2026",
        f"common bugs and known issues in {topic} 2026",
    ]
    for query in queries:
        try:
            result = answer(query, engine="all", freshness="month")
        except Exception:
            continue
        if not result or len(result) < 40:
            continue
        kind = "new_feature" if "feature" in query else "known_issue"
        created.append(
            store.propose(
                kind=kind,
                description=f"Online scan: {query[:120]}",
                candidate={
                    "query": query,
                    "summary": result[:2000],
                    "source": "web_scan",
                    "needs_approval": True,
                },
            )
        )
        if len(created) >= limit:
            break
    return created