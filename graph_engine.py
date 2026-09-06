"""Graph creation and graph analysis engine for structured visual knowledge."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


class GraphEngine:
    """Provides graph generation (Mermaid, ASCII, SVG, Chart.js) and graph reading/parsing."""

    @staticmethod
    def create_graph(
        nodes: List[Dict[str, str]],
        edges: List[Dict[str, str]],
        graph_type: str = "flowchart",
        direction: str = "TD",
    ) -> Dict[str, Any]:
        """Create graph representations in multiple formats (Mermaid, ASCII, and raw JSON).

        Args:
            nodes: list of {"id": "A", "label": "Node Label", "shape": "box"}
            edges: list of {"from": "A", "to": "B", "label": "Relation", "style": "solid"}
            graph_type: "flowchart", "sequencediagram", "erDiagram", "stateDiagram"
            direction: "TD" (Top-Down), "LR" (Left-Right)
        """
        mermaid_lines = []
        if graph_type == "flowchart":
            mermaid_lines.append(f"flowchart {direction}")
            for n in nodes:
                nid = n.get("id", "").strip()
                label = n.get("label", nid).replace('"', "'")
                mermaid_lines.append(f'    {nid}["{label}"]')
            for e in edges:
                src = e.get("from", "").strip()
                dst = e.get("to", "").strip()
                label = e.get("label")
                if label:
                    mermaid_lines.append(f'    {src} -->|"{label}"| {dst}')
                else:
                    mermaid_lines.append(f"    {src} --> {dst}")

        elif graph_type == "sequencediagram":
            mermaid_lines.append("sequenceDiagram")
            for e in edges:
                src = e.get("from", "ActorA")
                dst = e.get("to", "ActorB")
                label = e.get("label", "Message")
                mermaid_lines.append(f"    {src}->>{dst}: {label}")

        elif graph_type == "stateDiagram":
            mermaid_lines.append("stateDiagram-v2")
            for e in edges:
                src = e.get("from", "[*]")
                dst = e.get("to", "State1")
                label = e.get("label", "")
                if label:
                    mermaid_lines.append(f"    {src} --> {dst}: {label}")
                else:
                    mermaid_lines.append(f"    {src} --> {dst}")

        mermaid_code = "\n".join(mermaid_lines)

        # Generate simple ASCII representation
        ascii_lines = ["Graph Representation:"]
        for e in edges:
            src_label = next((n.get("label", n["id"]) for n in nodes if n["id"] == e.get("from")), e.get("from"))
            dst_label = next((n.get("label", n["id"]) for n in nodes if n["id"] == e.get("to")), e.get("to"))
            rel = f" --[{e.get('label')}]--> " if e.get("label") else " ----> "
            ascii_lines.append(f"  [{src_label}]{rel}[{dst_label}]")

        return {
            "graph_type": graph_type,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "mermaid": mermaid_code,
            "ascii": "\n".join(ascii_lines),
            "nodes": nodes,
            "edges": edges,
        }

    @staticmethod
    def read_graph(text: str) -> Dict[str, Any]:
        """Extract entities and relationship edges from plain text, Mermaid code, or Markdown."""
        nodes: Dict[str, Dict[str, str]] = {}
        edges: List[Dict[str, str]] = []

        # Parse Mermaid flowchart syntax if present
        mermaid_edge_pat = re.compile(
            r"(\w+)\s*(?:\[\"?([^\"]*?)\"?\])?\s*(-->|-->\|\"?([^\"]*?)\"?\||->>)\s*(\w+)\s*(?:\[\"?([^\"]*?)\"?\])?",
            re.MULTILINE,
        )
        for match in mermaid_edge_pat.finditer(text):
            src_id, src_lbl, arrow, label_inline, dst_id, dst_lbl = match.groups()
            nodes[src_id] = {"id": src_id, "label": src_lbl or src_id}
            nodes[dst_id] = {"id": dst_id, "label": dst_lbl or dst_id}
            edges.append({
                "from": src_id,
                "to": dst_id,
                "label": label_inline or "",
            })

        # Parse simple "A connects to B" or "A -> B" natural language statements
        nl_pat = re.compile(r"([A-Z][a-zA-Z0-9_\s]{1,30})\s+(?:connects to|depends on|calls|leads to|->)\s+([A-Z][a-zA-Z0-9_\s]{1,30})")
        for match in nl_pat.finditer(text):
            src, dst = match.group(1).strip(), match.group(2).strip()
            src_id = re.sub(r"\W+", "_", src).lower()
            dst_id = re.sub(r"\W+", "_", dst).lower()
            if src_id not in nodes:
                nodes[src_id] = {"id": src_id, "label": src}
            if dst_id not in nodes:
                nodes[dst_id] = {"id": dst_id, "label": dst}
            edges.append({"from": src_id, "to": dst_id, "label": ""})

        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }
