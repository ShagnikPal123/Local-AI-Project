"""Strands — the live graph of connected ideas (ROADMAP DD1, DD2).

The centre of the HUD tab. A strand is a link between two things the system
actually knows about: a memory, an agent's goal, an open chat, a knowledge entry.

The hard rule for this module, and for the tab that renders it: **every node is a
real object with somewhere to go.** The reference mockup Shagnik supplied is a
design, and every number in it is invented. A HUD that draws a beautiful graph of
nothing looks authoritative while telling the user less than an empty screen
would. If there is no data, this returns no nodes and the UI says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Words too common to imply a real connection between two ideas.
_STOPWORDS = frozenset("""
a an and are as at be but by for from has have how i if in into is it its of on
or that the their then there these this to was were what when where which who
will with you your me my we our not no do does did can could should would about
""".split())

_WORD_RE = re.compile(r"[a-z][a-z0-9_-]{2,}")

# Below this, two items share only incidental vocabulary.
_MIN_SHARED_TERMS = 2


@dataclass
class StrandNode:
    """One thing the system knows about."""

    node_id: str
    label: str
    kind: str          # memory | agent | chat | knowledge
    detail: str = ""
    # Where clicking this node should take the user. Empty means nowhere yet,
    # which the UI renders as non-interactive rather than as a dead link.
    target: str = ""
    terms: Set[str] = field(default_factory=set, repr=False)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.node_id,
            "label": self.label,
            "kind": self.kind,
            "detail": self.detail,
            "target": self.target,
        }


def _terms(*texts: str) -> Set[str]:
    """Significant words in a piece of text, for overlap comparison."""
    found: Set[str] = set()
    for text in texts:
        for match in _WORD_RE.finditer((text or "").lower()):
            word = match.group(0)
            if word not in _STOPWORDS:
                found.add(word)
    return found


def _edges(nodes: Sequence[StrandNode]) -> List[Dict[str, Any]]:
    """Link nodes that share enough vocabulary to be genuinely related.

    Deliberately conservative. A graph where everything connects to everything
    conveys nothing, so a single shared word is not a strand.
    """
    links: List[Dict[str, Any]] = []
    for i, left in enumerate(nodes):
        for right in nodes[i + 1:]:
            shared = left.terms & right.terms
            if len(shared) >= _MIN_SHARED_TERMS:
                links.append({
                    "source": left.node_id,
                    "target": right.node_id,
                    "weight": len(shared),
                    "shared": sorted(shared)[:5],
                })
    return links


def _from_memory(memory: Any) -> List[StrandNode]:
    nodes: List[StrandNode] = []
    try:
        entries: Iterable[Dict[str, Any]] = memory.get_important() or []
    except Exception:
        return nodes
    for index, entry in enumerate(entries):
        topic = str(entry.get("topic", "") or "").strip()
        content = str(entry.get("content", "") or "").strip()
        if not topic and not content:
            continue
        nodes.append(StrandNode(
            node_id=f"mem-{index}",
            label=topic or content[:40],
            kind="memory",
            detail=content[:160],
            target="work",
            terms=_terms(topic, content),
        ))
    return nodes


def _from_agents(team: Any) -> List[StrandNode]:
    nodes: List[StrandNode] = []
    try:
        snapshot = team.snapshot()
    except Exception:
        return nodes
    for agent in snapshot.get("agents", []):
        goal = str(agent.get("goal", "") or "")
        nodes.append(StrandNode(
            node_id=f"agent-{agent.get('agent_id', len(nodes))}",
            label=str(agent.get("name", "agent")),
            kind="agent",
            detail=goal[:160] or "no goal set",
            target="agents",
            terms=_terms(str(agent.get("name", "")), goal),
        ))
    return nodes


def _from_chats(chat_ids: Sequence[str]) -> List[StrandNode]:
    return [
        StrandNode(
            node_id=f"chat-{chat_id}",
            label=str(chat_id),
            kind="chat",
            detail="Active conversation",
            target="chat",
            terms=_terms(str(chat_id)),
        )
        for chat_id in chat_ids
    ]


def build_strands(
    memory: Any = None,
    team: Any = None,
    chat_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Assemble the strand graph from live system state.

    Every argument is optional and every source is guarded: a missing or broken
    subsystem contributes nothing rather than failing the whole view. The HUD
    stays up even when part of the system is down, which is the point of a HUD.
    """
    nodes: List[StrandNode] = []
    sources: Dict[str, int] = {}

    if memory is not None:
        found = _from_memory(memory)
        sources["memory"] = len(found)
        nodes.extend(found)

    if team is not None:
        found = _from_agents(team)
        sources["agents"] = len(found)
        nodes.extend(found)

    if chat_ids:
        found = _from_chats(chat_ids)
        sources["chats"] = len(found)
        nodes.extend(found)

    links = _edges(nodes)
    return {
        "nodes": [n.as_dict() for n in nodes],
        "links": links,
        "counts": {
            "nodes": len(nodes),
            "links": len(links),
            "by_source": sources,
        },
        # Told plainly so the UI can render an honest empty state rather than
        # inventing a decorative graph.
        "empty": not nodes,
    }
