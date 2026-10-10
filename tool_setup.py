"""Register every tool module once, and remember which ones failed to load.

Tools live in several modules (agents, the workspace landscape, machine access,
computer control, email, voice, system specs). Each exposes a
``register_*_tools(registry)`` function. A module that fails to import — a
missing optional package on someone's machine — must cost that module's tools,
not the whole assistant, and the failure must be visible (``/api/tools``)
rather than showing up as the model silently lacking an ability.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Tuple

#: (module, registration function). Order only matters for prompt readability.
TOOL_MODULES: List[Tuple[str, str]] = [
    ("agent_runtime", "register_agent_tools"),
    ("agent_dispatch", "register_dispatch_tools"),
    ("handoff_tools", "register_handoff_tools"),
    ("feature_catalog", "register_feature_tools"),
    ("curiosity", "register_curiosity_tools"),
    ("file_guard", "register_security_tools"),
    ("research_engine", "register_research_tools"),
    ("context_budget", "register_context_tools"),
    ("landscape_tools", "register_landscape_tools"),
    ("mods", "register_mod_tools"),
    ("media_tools", "register_media_tools"),
    ("system_info", "register_system_tools"),
    ("machine_tools", "register_machine_tools"),
    ("computer_control", "register_computer_tools"),
    ("own_computer", "register_own_computer_tools"),
    ("whatsapp_link", "register_whatsapp_tools"),
    ("site_preview", "register_preview_tools"),
    ("morning_digest", "register_digest_tools"),
    ("design_research", "register_research_tools"),
    ("email_client", "register_email_tools"),
    ("tts", "register_voice_tools"),
    ("improve_tools", "register_improve_tools"),
    ("intelligence_tools", "register_intelligence_tools"),
    ("chat_tools", "register_chat_tools"),
    ("court", "register_court_tools"),
    ("office_world_tools", "register_office_world_tools"),
    ("chat_modes", "register_chat_mode_tools"),
    ("design_sense", "register_design_tools"),
    ("backgrounds", "register_background_tools"),
    ("routes_notes", "register_notes_tools"),
    ("routes_trading", "register_trading_tools"),
    ("routes_build", "register_build_tools"),
    ("routes_game", "register_game_tools"),
    ("command_zone", "register_command_zone_tools"),
    ("absorb_engine", "register_absorb_tools"),
    ("data_process", "register_data_tools"),
    ("diagram_engine", "register_diagram_tools"),
    ("freewill", "register_freewill_tools"),
    ("identity0.tools", "register_identity0_tools"),
    ("connector_use", "register_connector_tools"),
    ("model_autoassign", "register_autoassign_tools"),
]

_lock = threading.Lock()
_status: Dict[str, Dict[str, Any]] = {}
_done = False


def register_all_tools(registry: Any = None, force: bool = False) -> Dict[str, Dict[str, Any]]:
    """Idempotent. Returns ``{module: {"ok": bool, "error": str, "tools": [...]}}``."""
    global _done
    from tools import TOOL_REGISTRY

    registry = registry or TOOL_REGISTRY
    with _lock:
        if _done and not force:
            return dict(_status)
        import importlib

        for module_name, function_name in TOOL_MODULES:
            # By handler, so a module that upgrades a built-in (tts's `speak`) lists it too.
            before = {name: tool.handler for name, tool in registry.tools.items()}
            try:
                module = importlib.import_module(module_name)
            except ModuleNotFoundError as error:
                if error.name == module_name:
                    _status[module_name] = {"ok": False, "error": "not installed yet", "tools": []}
                    continue
                _status[module_name] = {"ok": False, "error": f"missing dependency: {error.name}", "tools": []}
                continue
            except Exception as error:  # noqa: BLE001 - one broken module must not take the rest down
                _status[module_name] = {"ok": False, "error": f"{type(error).__name__}: {error}", "tools": []}
                continue
            register = getattr(module, function_name, None)
            if not callable(register):
                _status[module_name] = {"ok": False, "error": f"{function_name} not defined", "tools": []}
                continue
            try:
                register(registry)
                changed = [name for name, tool in registry.tools.items() if before.get(name) is not tool.handler]
                _status[module_name] = {"ok": True, "error": "", "tools": sorted(changed)}
            except Exception as error:  # noqa: BLE001
                _status[module_name] = {"ok": False, "error": f"{type(error).__name__}: {error}", "tools": []}
        _done = True
        return dict(_status)


def registration_status() -> Dict[str, Dict[str, Any]]:
    with _lock:
        return dict(_status)
