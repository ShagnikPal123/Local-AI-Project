"""Base connector specifications and manifest data structures."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ConnectorManifest:
    """Metadata describing a connector's capabilities, permissions, and risk profile."""

    name: str
    description: str
    permissions: List[str] = field(default_factory=lambda: ["read"])
    is_offline: bool = True
    requires_auth: bool = False
    is_write: bool = False
    risk_level: str = "low"  # "low", "medium", "high"
    config_schema: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize manifest to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "permissions": list(self.permissions),
            "is_offline": self.is_offline,
            "requires_auth": self.requires_auth,
            "is_write": self.is_write,
            "risk_level": self.risk_level,
            "config_schema": self.config_schema,
        }


class BaseConnector(ABC):
    """Abstract base class for all connectors and tool adapters."""

    @property
    @abstractmethod
    def manifest(self) -> ConnectorManifest:
        """Return the manifest describing this connector."""
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this connector is currently ready and configured for use."""
        raise NotImplementedError

    @abstractmethod
    def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Execute a specific action provided by this connector."""
        raise NotImplementedError

    def health_check(self) -> Dict[str, Any]:
        """Check connector health and return diagnostic status."""
        available = self.is_available()
        return {
            "name": self.manifest.name,
            "available": available,
            "status": "healthy" if available else "unavailable",
            "is_offline": self.manifest.is_offline,
            "risk_level": self.manifest.risk_level,
        }
