"""Tests for the Obsidian Local REST API & Vault Connector and tools."""

from unittest.mock import MagicMock, patch
import pytest
from connectors.obsidian_connector import ObsidianConnector, _DEFAULT_API_KEY
from connectors import CONNECTOR_REGISTRY
import tools


def test_obsidian_manifest():
    conn = ObsidianConnector()
    manifest = conn.manifest
    assert manifest.name == "obsidian"
    assert "read" in manifest.permissions
    assert "write" in manifest.permissions
    assert manifest.is_write is True


def test_obsidian_available_with_api_key():
    conn = ObsidianConnector(api_key="custom_token")
    assert conn.is_available() is True


def test_obsidian_filesystem_fallback(tmp_path):
    vault_dir = tmp_path / "test_vault"
    vault_dir.mkdir()
    (vault_dir / "CustomNote.md").write_text("# Welcome to Vault\nInitial notes", encoding="utf-8")

    conn = ObsidianConnector(api_key="", vault_path=str(vault_dir))

    # Read
    res = conn.execute("read", path="CustomNote.md")
    assert res["success"] is True
    assert "Welcome to Vault" in res["content"]

    # Append
    app_res = conn.execute("append", path="CustomNote.md", content="Appended text")
    assert app_res["success"] is True
    read_again = conn.execute("read", path="CustomNote.md")
    assert "Appended text" in read_again["content"]

    # Write new
    w_res = conn.execute("write", path="Ideas/Project.md", content="# New Idea\nLet's build an AI.")
    assert w_res["success"] is True
    assert (vault_dir / "Ideas" / "Project.md").exists()

    # List
    list_res = conn.execute("list")
    assert list_res["success"] is True
    assert list_res["count"] >= 2

    # Search
    search_res = conn.execute("search", query="AI")
    assert search_res["success"] is True
    assert any("Project.md" in m["filename"] for m in search_res["matches"])


def test_obsidian_rest_api_mock():
    conn = ObsidianConnector(api_key="mock_key")

    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"service": {"vault": "My Vault"}}

    with patch("requests.get", return_value=mock_response):
        status = conn.execute("status")
        assert status["success"] is True
        assert status["vault_name"] == "My Vault"
        assert status["api_reachable"] is True


def test_obsidian_tools_registered():
    for name in [
        "obsidian_search",
        "obsidian_read_note",
        "obsidian_write_note",
        "obsidian_append_note",
        "obsidian_list_notes",
    ]:
        tool = tools.TOOL_REGISTRY.get_tool(name)
        assert tool is not None, f"Expected {name} to be registered in TOOL_REGISTRY"
