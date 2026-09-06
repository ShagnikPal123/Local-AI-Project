"""Unit tests for the connectors adapter framework and policy confirmation gates."""

import pytest
from pathlib import Path
from connectors.base import ConnectorManifest
from connectors.policies import ConfirmationGate, ConfirmationRequiredError
from connectors.registry import ConnectorRegistry
from connectors.local_files import LocalFilesConnector
from connectors.web_search import WebSearchConnector
from connectors.app_launcher import AppLauncherConnector
from connectors.mcp import MCPConnector
from connectors.dynamic_tools import DynamicModularityConnector


def test_confirmation_gate_read_only():
    """Verify that read-only low-risk actions pass through without confirmation."""
    gate = ConfirmationGate()
    assert gate.verify_and_gate(
        connector_name="local_files",
        action="read_file",
        is_write=False,
        risk_level="low",
        params={"path": "README.md"},
    ) is True


def test_confirmation_gate_blocks_write():
    """Verify that write or high-risk actions raise ConfirmationRequiredError if not approved."""
    gate = ConfirmationGate()
    with pytest.raises(ConfirmationRequiredError):
        gate.verify_and_gate(
            connector_name="app_launcher",
            action="launch",
            is_write=True,
            risk_level="medium",
            params={"app_name": "calc"},
        )


def test_confirmation_gate_auto_approve():
    """Verify that auto_approve passes write operations."""
    gate = ConfirmationGate(auto_approve=True)
    assert gate.verify_and_gate(
        connector_name="app_launcher",
        action="launch",
        is_write=True,
        risk_level="medium",
        params={"app_name": "calc"},
    ) is True


def test_local_files_connector(tmp_path):
    """Test LocalFilesConnector file reading, directory listing, and safe sandboxing."""
    test_file = tmp_path / "sample.txt"
    test_file.write_text("Hello Nyx Ichos Connector", encoding="utf-8")

    connector = LocalFilesConnector(root_dir=tmp_path)
    assert connector.is_available() is True
    assert connector.manifest.name == "local_files"

    # Test read_file
    res = connector.execute("read_file", path="sample.txt")
    assert res["success"] is True
    assert "Hello Nyx Ichos Connector" in res["content"]

    # Test list_dir
    res_list = connector.execute("list_dir", path=".")
    assert res_list["success"] is True
    names = [i["name"] for i in res_list["items"]]
    assert "sample.txt" in names

    # Test search_files
    res_search = connector.execute("search_files", query="Nyx")
    assert res_search["success"] is True
    assert len(res_search["results"]) >= 1


def test_web_search_query_decomposition():
    """Test query decomposition in WebSearchConnector."""
    connector = WebSearchConnector()
    sub_queries = connector.decompose_query("Compare Python vs Rust and also explain async concurrency")
    assert len(sub_queries) >= 2


def test_app_launcher_command_resolver():
    """Test app command resolution in AppLauncherConnector."""
    launcher = AppLauncherConnector()
    cmd = launcher.find_app_command("notepad")
    assert cmd is not None
    assert len(cmd) > 0


def test_mcp_connector():
    """Test tool registration and execution in MCPConnector."""
    mcp = MCPConnector()
    mcp.register_mcp_tool(
        name="calculate_tax",
        description="Compute simple tax",
        parameters_schema={"amount": "number"},
        handler=lambda amount=100: f"Tax is {amount * 0.1}",
    )
    tools = mcp.list_mcp_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "calculate_tax"

    exec_res = mcp.execute("call_tool", tool_name="calculate_tax", arguments={"amount": 200})
    assert exec_res["success"] is True
    assert "20.0" in exec_res["result"]


def test_dynamic_modularity_connector(tmp_path):
    """Test dynamic AST scanning and function registration."""
    code = '''
def add_two(x, y):
    """Add two items together."""
    return x + y
'''
    py_file = tmp_path / "dynamic_lib.py"
    py_file.write_text(code, encoding="utf-8")

    dyn = DynamicModularityConnector()
    abilities = dyn.scan_file_for_abilities(py_file)
    assert len(abilities) == 1
    assert abilities[0]["name"] == "add_two"
    assert abilities[0]["description"] == "Add two items together."

    # Test dynamic registration
    reg = dyn.register_dynamic_function(
        name="add_two_test",
        description="Add two numbers dynamically",
        handler=lambda x=1, y=2: int(x) + int(y),
    )
    assert reg["registered"] is True
