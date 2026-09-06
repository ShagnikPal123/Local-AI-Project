"""Policy, permission checking, and confirmation gates for connectors."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class ConfirmationRequiredError(PermissionError):
    """Raised when an operation requires explicit user confirmation before execution."""


class SecurityViolationError(PermissionError):
    """Raised when an operation violates security policies."""


class ConfirmationGate:
    """Gatekeeper for sensitive, write, or system-level connector actions."""

    def __init__(
        self,
        confirmation_handler: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
        auto_approve: bool = False,
    ):
        self._confirmation_handler = confirmation_handler
        self._auto_approve = auto_approve

    def set_auto_approve(self, enabled: bool) -> None:
        """Toggle auto-approval (e.g., for automated non-interactive testing)."""
        self._auto_approve = enabled

    def set_handler(self, handler: Callable[[str, Dict[str, Any]], bool]) -> None:
        """Register interactive confirmation callback."""
        self._confirmation_handler = handler

    def verify_and_gate(
        self,
        connector_name: str,
        action: str,
        is_write: bool,
        risk_level: str,
        params: Dict[str, Any],
    ) -> bool:
        """Check if action is safe or requires human gate confirmation.

        Returns:
            True if action is approved to proceed.

        Raises:
            ConfirmationRequiredError: if action needs confirmation but is not approved.
        """
        # Read-only low-risk actions pass through automatically
        if not is_write and risk_level == "low":
            return True

        if self._auto_approve:
            logger.info("Auto-approved %s:%s (is_write=%s, risk=%s)", connector_name, action, is_write, risk_level)
            return True

        prompt = f"Action '{action}' on connector '{connector_name}' (risk: {risk_level}, write: {is_write}) requires confirmation."
        if self._confirmation_handler is not None:
            approved = self._confirmation_handler(prompt, {"connector": connector_name, "action": action, "params": params})
            if approved:
                return True
            raise ConfirmationRequiredError(f"User declined execution of '{action}' on '{connector_name}'.")

        raise ConfirmationRequiredError(
            f"Action '{action}' on connector '{connector_name}' requires explicit confirmation: {params}"
        )
