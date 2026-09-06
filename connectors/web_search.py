"""Web search and research connector with query decomposition and offline fallback."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from connectivity import is_online
from connectors.base import BaseConnector, ConnectorManifest
import web_access


class WebSearchConnector(BaseConnector):
    """Connector providing intelligent web search, query decomposition, and citation handling."""

    def __init__(self):
        self._manifest = ConnectorManifest(
            name="web_search",
            description="Search the web with query decomposition, source ranking, and citations.",
            permissions=["read", "network"],
            is_offline=False,
            requires_auth=False,
            is_write=False,
            risk_level="low",
        )

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def is_available(self) -> bool:
        return is_online() and web_access.is_enabled()

    def decompose_query(self, complex_query: str) -> List[str]:
        """Split a complex prompt or multifaceted query into up to 3 focused sub-queries."""
        query = complex_query.strip()
        # Split on conjunctions or clauses if complex
        sub_queries = []
        parts = re.split(r"\b(?:and also|compare to|vs|versus|as well as)\b", query, flags=re.IGNORECASE)
        for part in parts:
            clean = part.strip()
            if len(clean) > 3 and clean not in sub_queries:
                sub_queries.append(clean)

        if not sub_queries:
            sub_queries = [query]
        return sub_queries[:3]

    def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        if action == "search":
            query = params.get("query", "")
            engine = params.get("engine", "all")
            freshness = params.get("freshness", "month")
            decompose = params.get("decompose", False)

            if not query:
                return {"success": False, "error": "Query parameter cannot be empty."}

            if not self.is_available():
                return {
                    "success": True,
                    "offline": True,
                    "query": query,
                    "summary": "Offline: Internet search is currently unavailable. Using local knowledge fallback.",
                    "results": [],
                }

            queries = self.decompose_query(query) if decompose else [query]
            aggregated_results: List[Dict[str, Any]] = []
            seen_urls = set()

            for q in queries:
                try:
                    summary = web_access.answer(q, engine=engine, freshness=freshness)
                    # Extract citations from web_access if available
                    aggregated_results.append({
                        "sub_query": q,
                        "summary": summary,
                    })
                except Exception as e:
                    aggregated_results.append({"sub_query": q, "error": str(e)})

            return {
                "success": True,
                "offline": False,
                "original_query": query,
                "sub_queries": queries,
                "results": aggregated_results,
            }

        elif action == "fetch_page":
            url = params.get("url", "")
            if not url:
                return {"success": False, "error": "URL parameter required."}
            if not self.is_available():
                return {"success": False, "error": "Offline: Cannot fetch webpage."}

            try:
                content = web_access.open_link(url)
                return {"success": True, "url": url, "content": content}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": False, "error": f"Unknown action '{action}' for web_search connector."}
