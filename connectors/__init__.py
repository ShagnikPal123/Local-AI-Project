"""Unified Connectors and Tools Adapter Package for Nyx Ichos."""

from __future__ import annotations

from connectors.base import BaseConnector, ConnectorManifest
from connectors.policies import (
    ConfirmationGate,
    ConfirmationRequiredError,
    SecurityViolationError,
)
from connectors.registry import CONNECTOR_REGISTRY, ConnectorRegistry
from connectors.local_files import LocalFilesConnector
from connectors.web_search import WebSearchConnector
from connectors.app_launcher import AppLauncherConnector
from connectors.mcp import MCPConnector
from connectors.dynamic_tools import DynamicModularityConnector
from connectors.system_control import SystemControlConnector
from connectors.google_connector import GoogleConnector
from connectors.youtube_connector import YouTubeConnector
from connectors.finance_connector import FinanceConnector
from connectors.voice_connector import VoiceConnector
from connectors.obsidian_connector import ObsidianConnector
from connectors.apple_design_connector import AppleDesignConnector

# Register default core connectors
CONNECTOR_REGISTRY.register(LocalFilesConnector())
CONNECTOR_REGISTRY.register(WebSearchConnector())
CONNECTOR_REGISTRY.register(AppLauncherConnector())
CONNECTOR_REGISTRY.register(MCPConnector())
CONNECTOR_REGISTRY.register(DynamicModularityConnector())
CONNECTOR_REGISTRY.register(SystemControlConnector())
CONNECTOR_REGISTRY.register(GoogleConnector())
CONNECTOR_REGISTRY.register(YouTubeConnector())
CONNECTOR_REGISTRY.register(FinanceConnector())
CONNECTOR_REGISTRY.register(VoiceConnector())
CONNECTOR_REGISTRY.register(ObsidianConnector())
CONNECTOR_REGISTRY.register(AppleDesignConnector())

__all__ = [
    "AppleDesignConnector",
    "AppLauncherConnector",
    "BaseConnector",
    "CONNECTOR_REGISTRY",
    "ConfirmationGate",
    "ConfirmationRequiredError",
    "ConnectorManifest",
    "ConnectorRegistry",
    "DynamicModularityConnector",
    "FinanceConnector",
    "GoogleConnector",
    "LocalFilesConnector",
    "MCPConnector",
    "SecurityViolationError",
    "SystemControlConnector",
    "VoiceConnector",
    "WebSearchConnector",
    "YouTubeConnector",
]
