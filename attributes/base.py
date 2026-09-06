"""Base dataclass for Nyx Ichos attributes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Attribute:
    """Immutable behavior profile used to shape assistant guidance.

    Attributes are metadata-only and intentionally do not call providers,
    execute tools, or decide routing logic. The router remains responsible for
    actual provider/model decisions.
    """

    id: str
    display_name: str
    description: str
    system_guidance: str
    response_style: str = "balanced"
    preferred_task_type: Optional[str] = None
    local_only: bool = False

    def __post_init__(self) -> None:
        """Validate the attribute fields are non-empty and normalized."""
        for field_name in ("id", "display_name", "description", "system_guidance"):
            value = getattr(self, field_name)
            if value is None or not str(value).strip():
                raise ValueError(f"Attribute.{field_name} must be a non-empty string.")

        object.__setattr__(self, "id", str(self.id).strip())
        object.__setattr__(self, "display_name", str(self.display_name).strip())
        object.__setattr__(self, "description", str(self.description).strip())
        object.__setattr__(self, "system_guidance", str(self.system_guidance).strip())
        object.__setattr__(self, "response_style", str(self.response_style).strip())

        if self.preferred_task_type is not None:
            object.__setattr__(
                self,
                "preferred_task_type",
                str(self.preferred_task_type).strip() or None,
            )


class AttributeNotFoundError(LookupError):
    """Raised when an attribute ID is missing from the registry."""

    pass
