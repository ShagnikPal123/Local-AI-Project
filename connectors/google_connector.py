"""Google Services and control connector (Google Search, Maps, Drive, Docs, Calendar)."""

from __future__ import annotations

import logging
import urllib.parse
import webbrowser
from typing import Any, Dict, List, Optional

from connectors.base import BaseConnector, ConnectorManifest
import web_access

logger = logging.getLogger(__name__)


class GoogleConnector(BaseConnector):
    """Integrates with Google Services (Search, Maps, Drive, Docs, Calendar)."""

    def __init__(self):
        self._manifest = ConnectorManifest(
            name="google_services",
            description="Control and interact with Google Services (Google Search, Maps, Drive, Docs, Calendar).",
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
        return True

    def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        if action == "search":
            return self._search(params.get("query", ""), open_in_browser=params.get("open_browser", False))
        elif action == "maps":
            return self._maps(params.get("location", ""), destination=params.get("destination"), open_in_browser=params.get("open_browser", False))
        elif action == "drive_search":
            return self._drive_search(params.get("query", ""), open_in_browser=params.get("open_browser", False))
        elif action == "create_doc":
            return self._create_doc(doc_type=params.get("doc_type", "document"), open_in_browser=params.get("open_browser", True))
        elif action == "create_calendar_event":
            return self._create_calendar_event(
                title=params.get("title", "New Event"),
                details=params.get("details", ""),
                location=params.get("location", ""),
                open_in_browser=params.get("open_browser", False),
            )
        else:
            return {"success": False, "error": f"Unknown action '{action}' for google_services connector."}

    def _search(self, query: str, open_in_browser: bool = False) -> Dict[str, Any]:
        if not query:
            return {"success": False, "error": "Search query cannot be empty."}
        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.google.com/search?q={encoded}"

        summary = ""
        try:
            summary = web_access.answer(query, engine="google")
        except Exception:
            pass

        if open_in_browser:
            webbrowser.open(url)

        return {
            "success": True,
            "query": query,
            "url": url,
            "summary": summary,
            "browser_opened": open_in_browser,
        }

    def _maps(self, location: str, destination: Optional[str] = None, open_in_browser: bool = False) -> Dict[str, Any]:
        if not location:
            return {"success": False, "error": "Location parameter required."}
        if destination:
            url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote_plus(location)}&destination={urllib.parse.quote_plus(destination)}"
        else:
            url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(location)}"

        if open_in_browser:
            webbrowser.open(url)

        return {
            "success": True,
            "location": location,
            "destination": destination,
            "url": url,
            "browser_opened": open_in_browser,
        }

    def _drive_search(self, query: str, open_in_browser: bool = False) -> Dict[str, Any]:
        url = f"https://drive.google.com/drive/search?q={urllib.parse.quote_plus(query)}" if query else "https://drive.google.com/"
        if open_in_browser:
            webbrowser.open(url)
        return {"success": True, "query": query, "url": url, "browser_opened": open_in_browser}

    def _create_doc(self, doc_type: str = "document", open_in_browser: bool = True) -> Dict[str, Any]:
        urls = {
            "document": "https://docs.new",
            "doc": "https://docs.new",
            "sheet": "https://sheets.new",
            "spreadsheet": "https://sheets.new",
            "slide": "https://slides.new",
            "presentation": "https://slides.new",
            "form": "https://forms.new",
        }
        target_url = urls.get(doc_type.lower(), "https://docs.new")
        if open_in_browser:
            webbrowser.open(target_url)
        return {"success": True, "doc_type": doc_type, "url": target_url, "browser_opened": open_in_browser}

    def _create_calendar_event(
        self,
        title: str,
        details: str = "",
        location: str = "",
        open_in_browser: bool = False,
    ) -> Dict[str, Any]:
        params = {
            "action": "TEMPLATE",
            "text": title,
            "details": details,
            "location": location,
        }
        url = f"https://calendar.google.com/calendar/render?{urllib.parse.urlencode(params)}"
        if open_in_browser:
            webbrowser.open(url)
        return {"success": True, "title": title, "url": url, "browser_opened": open_in_browser}
