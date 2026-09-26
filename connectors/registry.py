"""Central registry and dispatch engine for connectors."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from connectors.base import BaseConnector
from connectors.policies import ConfirmationGate

logger = logging.getLogger(__name__)


class ConnectorRegistry:
    """Registry managing available connectors, permissions, and policy enforcement."""

    #: How long an availability answer is reused. Some checks probe a local
    #: service (Obsidian's REST API), and on Windows a connection to a closed
    #: loopback port takes about two seconds to fail. Asked on every connector
    #: listing and before every action, that made the Connectors tab take four
    #: seconds to open and added seconds to every Obsidian tool call.
    AVAILABILITY_TTL_SECONDS = 30.0

    def __init__(self, confirmation_gate: Optional[ConfirmationGate] = None):
        self._connectors: Dict[str, BaseConnector] = {}
        self.gate = confirmation_gate or ConfirmationGate()
        self._availability: Dict[str, tuple] = {}
        self._availability_lock = threading.Lock()
        self._refreshing: set = set()

    def _refresh(self, key: str) -> None:
        try:
            self.is_available(key, fresh=True)
        finally:
            self._refreshing.discard(key)

    def warm(self) -> None:
        """Check every connector in the background so the first listing is instant."""
        threading.Thread(target=self._all_availability, name="nyx-connector-warmup", daemon=True).start()

    def is_available(self, name: str, fresh: bool = False) -> bool:
        """Cached ``is_available`` for one connector. Never raises."""
        key = name.lower().strip()
        conn = self._connectors.get(key)
        if conn is None:
            return False
        now = time.monotonic()
        with self._availability_lock:
            cached = self._availability.get(key)
        if not fresh and cached is not None:
            if now - cached[0] >= self.AVAILABILITY_TTL_SECONDS and key not in self._refreshing:
                # Stale: answer with what we know and re-check in the background,
                # so nobody waits on a slow probe after the first one.
                self._refreshing.add(key)
                threading.Thread(target=self._refresh, args=(key,), daemon=True).start()
            return cached[1]
        try:
            available = bool(conn.is_available())
        except Exception:
            available = False
        with self._availability_lock:
            self._availability[key] = (time.monotonic(), available)
        return available

    def _all_availability(self) -> Dict[str, bool]:
        """Availability of every connector, checked in parallel."""
        names = list(self._connectors)
        if not names:
            return {}
        with ThreadPoolExecutor(max_workers=min(8, len(names))) as pool:
            results = list(pool.map(self.is_available, names))
        return dict(zip(names, results))

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
        availability = self._all_availability()
        return [
            {
                **conn.manifest.to_dict(),
                "available": availability.get(name, False),
            }
            for name, conn in self._connectors.items()
        ]

    def execute(self, connector_name: str, action: str, **params: Any) -> Dict[str, Any]:
        """Execute a connector action with policy and confirmation gating."""
        conn = self.get(connector_name)
        if not conn:
            return {"success": False, "error": f"Connector '{connector_name}' not found."}

        if not self.is_available(connector_name):
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
        availability = self._all_availability()
        return {
            name: {
                "name": conn.manifest.name,
                "available": availability.get(name, False),
                "status": "healthy" if availability.get(name, False) else "unavailable",
                "is_offline": conn.manifest.is_offline,
                "risk_level": conn.manifest.risk_level,
            }
            for name, conn in self._connectors.items()
        }


# Global singleton registry
CONNECTOR_REGISTRY = ConnectorRegistry()
