"""Dynamic Modularity connector enabling self-sufficient ability expansion."""

from __future__ import annotations

import ast
import inspect
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from connectors.base import BaseConnector, ConnectorManifest
from tools import TOOL_REGISTRY, ToolParam

logger = logging.getLogger(__name__)


class DynamicModularityConnector(BaseConnector):
    """Allows scanning source files or code strings to dynamically register new abilities."""

    def __init__(self):
        self._manifest = ConnectorManifest(
            name="dynamic_modularity",
            description="Scan files or scripts to dynamically discover and register new abilities/tools into the assistant.",
            permissions=["read", "execute"],
            is_offline=True,
            requires_auth=False,
            is_write=False,
            risk_level="medium",
        )
        self._registered_abilities: Dict[str, Dict[str, Any]] = {}

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def is_available(self) -> bool:
        return True

    def scan_file_for_abilities(self, file_path: str | Path) -> List[Dict[str, Any]]:
        """Parse a Python source file with AST to discover exported functions with docstrings."""
        path = Path(file_path).resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))

        discovered = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                docstring = ast.get_docstring(node) or f"Dynamic function {node.name}"
                params = [arg.arg for arg in node.args.args]
                discovered.append({
                    "name": node.name,
                    "description": docstring,
                    "params": params,
                    "file": str(path),
                })
        return discovered

    def register_dynamic_function(
        self,
        name: str,
        description: str,
        handler: Callable[..., Any],
        param_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Register a callable function dynamically into TOOL_REGISTRY."""
        if not callable(handler):
            raise TypeError(f"Handler for '{name}' must be callable.")

        clean_name = name.strip().lower()
        sig = inspect.signature(handler)
        tool_params: List[ToolParam] = []

        for p_name, param in sig.parameters.items():
            req = param.default == inspect.Parameter.empty
            tool_params.append(
                ToolParam(
                    name=p_name,
                    param_type="string",
                    description=f"Parameter {p_name}",
                    required=req,
                )
            )

        # Register in global tool registry
        TOOL_REGISTRY.register(
            name=clean_name,
            description=description,
            parameters=tool_params,
            handler=lambda **kwargs: str(handler(**kwargs)),
        )

        ability_record = {
            "name": clean_name,
            "description": description,
            "params": [p.name for p in tool_params],
            "registered": True,
        }
        self._registered_abilities[clean_name] = ability_record
        return ability_record

    def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        if action == "scan_file":
            file_path = params.get("path", "")
            if not file_path:
                return {"success": False, "error": "path parameter is required."}
            try:
                abilities = self.scan_file_for_abilities(file_path)
                return {"success": True, "path": file_path, "abilities": abilities}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif action == "list_abilities":
            return {"success": True, "abilities": list(self._registered_abilities.values())}

        return {"success": False, "error": f"Unknown action '{action}' for dynamic_modularity connector."}
