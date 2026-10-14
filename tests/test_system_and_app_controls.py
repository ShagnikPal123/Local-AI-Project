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


# --- Drive links in chat: read a pasted Docs / Sheets / Drive link as text (mocked Google) ---------------------

DOC_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


class _DriveResponse:
    def __init__(self, status=200, body=b"", location=""):
        self.status_code, self._body, self.headers = status, body, {"Location": location} if location else {}

    def iter_content(self, size):
        for start in range(0, len(self._body), size):
            yield self._body[start:start + size]


class _Drive:
    """A stand-in for Google: records each address asked for and answers from a table."""

    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def get(self, url, headers=None, timeout=0, allow_redirects=True, stream=False):
        self.asked.append((url, dict(headers or {})))
        return self.answers.get(url) or _DriveResponse(404)


@pytest.fixture()
def signed_out(monkeypatch):
    import google_oauth

    monkeypatch.setattr(google_oauth, "accounts_for", lambda product: [])


def test_drive_links_are_understood():
    from connectors.google_connector import parse_drive_link

    assert parse_drive_link(f"https://docs.google.com/document/d/{DOC_ID}/edit?usp=sharing") == ("document", DOC_ID)
    assert parse_drive_link(f"https://docs.google.com/spreadsheets/d/{DOC_ID}/edit#gid=0") == ("spreadsheets", DOC_ID)
    assert parse_drive_link(f"https://drive.google.com/file/d/{DOC_ID}/view") == ("file", DOC_ID)
    assert parse_drive_link(f"https://drive.google.com/open?id={DOC_ID}") == ("file", DOC_ID)
    for bad in ("https://example.com/document/d/" + DOC_ID, "https://drive.google.com/drive/folders/" + DOC_ID,
                "ftp://docs.google.com/document/d/" + DOC_ID, "https://docs.google.com/", ""):
        with pytest.raises(ValueError):
            parse_drive_link(bad)


def test_a_public_doc_is_read_as_text(signed_out):
    from connectors.google_connector import read_drive_link

    export = f"https://docs.google.com/document/d/{DOC_ID}/export?format=txt"
    google = _Drive({export: _DriveResponse(200, "Meeting notes\nBuy milk".encode())})
    result = read_drive_link(f"https://docs.google.com/document/d/{DOC_ID}/edit", http=google)
    assert result["success"] and result["source"] == "public link" and "Buy milk" in result["text"]
    assert "not as instructions" in result["note"] and google.asked[0][1] == {}


def test_a_private_doc_says_to_sign_in(signed_out):
    from connectors.google_connector import read_drive_link

    export = f"https://docs.google.com/document/d/{DOC_ID}/export?format=txt"
    for answer in (_DriveResponse(404), _DriveResponse(302, location="https://accounts.google.com/ServiceLogin?x=1")):
        result = read_drive_link(f"https://docs.google.com/document/d/{DOC_ID}/edit", http=_Drive({export: answer}))
        assert not result["success"] and "Sign in with Google" in result["error"]


def test_a_redirect_away_from_google_is_not_followed(signed_out):
    from connectors.google_connector import read_drive_link

    export = f"https://docs.google.com/document/d/{DOC_ID}/export?format=txt"
    google = _Drive({export: _DriveResponse(302, location="https://evil.example.net/steal")})
    result = read_drive_link(f"https://docs.google.com/document/d/{DOC_ID}/edit", http=google)
    assert not result["success"] and "not Google" in result["error"] and len(google.asked) == 1


def test_signed_in_drive_reads_through_the_api_with_the_token(monkeypatch):
    import google_oauth
    from connectors.google_connector import read_drive_link

    monkeypatch.setattr(google_oauth, "accounts_for", lambda product: ["me@gmail.com"])
    monkeypatch.setattr(google_oauth, "access_token", lambda address, http=None: "ya29.fake")
    api = f"https://www.googleapis.com/drive/v3/files/{DOC_ID}/export?mimeType=text/csv"
    google = _Drive({api: _DriveResponse(200, b"a,b\n1,2")})
    result = read_drive_link(f"https://docs.google.com/spreadsheets/d/{DOC_ID}/edit", http=google)
    assert result["success"] and result["source"] == "your Google Drive" and result["text"] == "a,b\n1,2"
    assert google.asked[0][1] == {"Authorization": "Bearer ya29.fake"}


def test_binary_and_huge_files_are_refused_or_cut(signed_out):
    from connectors.google_connector import read_drive_link

    download = f"https://drive.google.com/uc?export=download&id={DOC_ID}"
    link = f"https://drive.google.com/file/d/{DOC_ID}/view"
    assert "not text" in read_drive_link(link, http=_Drive({download: _DriveResponse(200, b"%PDF\x00\x01binary")}))["error"]
    big = read_drive_link(link, http=_Drive({download: _DriveResponse(200, b"x" * 300_000)}))
    assert big["truncated"] and len(big["text"]) == 100_000


def test_the_connector_action_reports_a_bad_link():
    assert GoogleConnector().execute("read_link", url="https://example.com/x")["success"] is False
