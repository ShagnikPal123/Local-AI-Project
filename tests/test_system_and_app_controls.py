"""Unit tests for Computer System Controls, Google Services, and YouTube Connectors."""

import pytest
from unittest.mock import patch, MagicMock
from connectors.system_control import SystemControlConnector
from connectors.google_connector import GoogleConnector
from connectors.youtube_connector import YouTubeConnector
from tools import TOOL_REGISTRY


def test_system_control_manifest_and_stats():
    """Verify SystemControlConnector manifest properties and stats."""
    conn = SystemControlConnector()
    assert conn.manifest.name == "system_control"
    assert conn.manifest.is_write is True
    assert conn.manifest.risk_level == "medium"
    assert conn.is_available() is True

    stats = conn.execute("get_system_stats")
    assert stats["success"] is True
    assert "os" in stats
    assert "cpu_cores" in stats


def test_system_control_clipboard_and_screenshot(tmp_path):
    """Test clipboard read/write simulation and screenshot execution."""
    conn = SystemControlConnector()

    # Test clipboard get with mock
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="Mocked Clipboard Content")
        res = conn.execute("get_clipboard")
        assert res["success"] is True
        assert res["clipboard"] == "Mocked Clipboard Content"

    # Test screenshot with mock
    with patch.object(conn, "_take_screenshot") as mock_ss:
        mock_ss.return_value = {"success": True, "path": "test_ss.png"}
        res = conn.execute("take_screenshot", output_path="test_ss.png")
        assert res["success"] is True
        assert res["path"] == "test_ss.png"


def test_google_connector_search_and_maps():
    """Verify GoogleConnector search and maps URL construction."""
    google = GoogleConnector()
    assert google.manifest.name == "google_services"
    assert google.is_available() is True

    # Search
    s_res = google.execute("search", query="FastAPI Python tutorial", open_browser=False)
    assert s_res["success"] is True
    assert "google.com/search?q=FastAPI+Python+tutorial" in s_res["url"]

    # Maps
    m_res = google.execute("maps", location="Central Park, NY", open_browser=False)
    assert m_res["success"] is True
    assert "google.com/maps" in m_res["url"]
    assert "Central+Park" in m_res["url"]

    # Docs
    d_res = google.execute("create_doc", doc_type="sheet", open_browser=False)
    assert d_res["success"] is True
    assert d_res["url"] == "https://sheets.new"


def test_youtube_connector_search_and_play():
    """Verify YouTubeConnector search, video ID extraction, and playback URL building."""
    yt = YouTubeConnector()
    assert yt.manifest.name == "youtube"
    assert yt.is_available() is True

    # Extract video ID
    vid_id = yt.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert vid_id == "dQw4w9WgXcQ"

    short_id = yt.extract_video_id("https://youtu.be/dQw4w9WgXcQ")
    assert short_id == "dQw4w9WgXcQ"

    # Search
    with patch("webbrowser.open"):
        s_res = yt.execute("search", query="lofi hip hop radio", open_browser=False)
        assert s_res["success"] is True
        assert "youtube.com/results?search_query=lofi+hip+hop+radio" in s_res["search_url"]

        # Play video
        p_res = yt.execute("play", query_or_url="dQw4w9WgXcQ", music=False)
        assert p_res["success"] is True
        assert p_res["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

        # Play music
        m_res = yt.execute("play", query_or_url="dQw4w9WgXcQ", music=True)
        assert m_res["success"] is True
        assert m_res["url"] == "https://music.youtube.com/watch?v=dQw4w9WgXcQ"

        # Video info
        info_res = yt.execute("get_video_info", video_id="dQw4w9WgXcQ")
        assert info_res["success"] is True
        assert "img.youtube.com" in info_res["thumbnail_url"]


def test_tools_registered():
    """Verify all new tools are discoverable in TOOL_REGISTRY."""
    tools = [t.name for t in TOOL_REGISTRY.list_tools()]
    assert "system_clipboard" in tools
    assert "system_screenshot" in tools
    assert "google_search" in tools
    assert "youtube_search" in tools
    assert "youtube_play" in tools
