"""Central registry and dispatch engine for connectors."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from connectors.base import BaseConnector
from connectors.policies import ConfirmationGate

logger = logging.getLogger(__name__)


class ConnectorRegistry:
    """Registry managing available connectors, permissions, and policy enforcement."""

    def __init__(self, confirmation_gate: Optional[ConfirmationGate] = None):
        self._connectors: Dict[str, BaseConnector] = {}
        self.gate = confirmation_gate or ConfirmationGate()

    def register(self, connector: BaseConnector) -> None:
        """Register a connector."""
        name = connector.manifest.name.lower().strip()
        self._connectors[name] = connector
        logger.debug("Registered connector: %s", name)

    def get(self, name: str) -> Optional[BaseConnector]:
        """Retrieve a connector by name."""
        return self._connectors.get(name.lower().strip())

    def list_connectors(self) -> List[Dict[str, Any]]:
        """List metadata for all registered connectors."""
        return [
            {
                **conn.manifest.to_dict(),
                "available": conn.is_available(),
            }
            for conn in self._connectors.values()
        ]

    def execute(self, connector_name: str, action: str, **params: Any) -> Dict[str, Any]:
        """Execute a connector action with policy and confirmation gating."""
        conn = self.get(connector_name)
        if not conn:
            return {"success": False, "error": f"Connector '{connector_name}' not found."}

        if not conn.is_available():
            return {"success": False, "error": f"Connector '{connector_name}' is currently unavailable."}

        manifest = conn.manifest
        # Check confirmation gate
        self.gate.verify_and_gate(
            connector_name=manifest.name,
            action=action,
            is_write=manifest.is_write,
            risk_level=manifest.risk_level,
            params=params,
        )

        try:
            return conn.execute(action, **params)
        except Exception as e:
            logger.exception("Error executing action '%s' on connector '%s'", action, connector_name)
            return {"success": False, "error": str(e)}

    def health_status(self) -> Dict[str, Any]:
        """Return health checks for all connectors."""
        return {name: conn.health_check() for name, conn in self._connectors.items()}


# Global singleton registry
CONNECTOR_REGISTRY = ConnectorRegistry()
