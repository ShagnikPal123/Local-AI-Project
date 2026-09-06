"""YouTube connector for searching videos, music playback, channel discovery, and URL parsing."""

from __future__ import annotations

import logging
import re
import urllib.parse
import webbrowser
from typing import Any, Dict, List, Optional

from connectors.base import BaseConnector, ConnectorManifest
import web_access

logger = logging.getLogger(__name__)


class YouTubeConnector(BaseConnector):
    """Integrates with YouTube for video search, audio/music playback, and links."""

    def __init__(self):
        self._manifest = ConnectorManifest(
            name="youtube",
            description="Search YouTube videos, play songs/music, extract video IDs, and open playback.",
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

    def extract_video_id(self, url_or_text: str) -> Optional[str]:
        """Extract an 11-character YouTube video ID from a URL or shortcode."""
        text = (url_or_text or "").strip()
        if re.match(r"^[0-9A-Za-z_-]{11}$", text):
            return text
        patterns = [
            r"(?:v=|\/)([0-9A-Za-z_-]{11})",
            r"youtu\.be\/([0-9A-Za-z_-]{11})",
            r"youtube\.com\/shorts\/([0-9A-Za-z_-]{11})",
            r"youtube\.com\/embed\/([0-9A-Za-z_-]{11})",
        ]
        for pat in patterns:
            match = re.search(pat, text)
            if match:
                return match.group(1)
        return None

    def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        if action == "search":
            return self._search(params.get("query", ""), open_in_browser=params.get("open_browser", False))
        elif action == "play":
            return self._play(params.get("query_or_url", ""), music_mode=params.get("music", False))
        elif action == "get_video_info":
            return self._get_video_info(params.get("video_id", ""))
        else:
            return {"success": False, "error": f"Unknown action '{action}' for youtube connector."}

    def _search(self, query: str, open_in_browser: bool = False) -> Dict[str, Any]:
        if not query:
            return {"success": False, "error": "Search query cannot be empty."}

        encoded = urllib.parse.quote_plus(query)
        search_url = f"https://www.youtube.com/results?search_query={encoded}"

        # Fetch snippet via web_access if available
        summary = ""
        try:
            summary = web_access.answer(f"YouTube videos for {query}", engine="all")
        except Exception:
            pass

        if open_in_browser:
            webbrowser.open(search_url)

        return {
            "success": True,
            "query": query,
            "search_url": search_url,
            "summary": summary,
            "browser_opened": open_in_browser,
        }

    def _play(self, query_or_url: str, music_mode: bool = False) -> Dict[str, Any]:
        if not query_or_url:
            return {"success": False, "error": "Query or URL parameter required."}

        video_id = self.extract_video_id(query_or_url)
        if video_id:
            if music_mode:
                target_url = f"https://music.youtube.com/watch?v={video_id}"
            else:
                target_url = f"https://www.youtube.com/watch?v={video_id}"
        else:
            encoded = urllib.parse.quote_plus(query_or_url)
            if music_mode:
                target_url = f"https://music.youtube.com/search?q={encoded}"
            else:
                target_url = f"https://www.youtube.com/results?search_query={encoded}"

        try:
            webbrowser.open(target_url)
            return {
                "success": True,
                "target": query_or_url,
                "url": target_url,
                "video_id": video_id,
                "music_mode": music_mode,
                "status": "opened",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_video_info(self, video_id_or_url: str) -> Dict[str, Any]:
        video_id = self.extract_video_id(video_id_or_url) or video_id_or_url.strip()
        if not video_id:
            return {"success": False, "error": "Valid video ID or URL required."}

        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        embed_url = f"https://www.youtube.com/embed/{video_id}"
        thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

        return {
            "success": True,
            "video_id": video_id,
            "watch_url": watch_url,
            "embed_url": embed_url,
            "thumbnail_url": thumbnail_url,
        }
