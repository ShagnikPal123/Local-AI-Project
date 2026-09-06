"""Registry for static Nyx Ichos attributes."""

from __future__ import annotations

from .base import Attribute, AttributeNotFoundError
from .presets import ATTRIBUTE_PRESETS


def list_attributes() -> list[Attribute]:
    """Return all built-in attributes in a deterministic order."""
    return list(ATTRIBUTE_PRESETS.values())


def get_attribute(attribute_id: str) -> Attribute:
    """Return a single attribute by ID.

    Raises:
        AttributeNotFoundError: if the attribute ID is unknown.
    """
    if not isinstance(attribute_id, str):
        raise AttributeNotFoundError(f"Attribute ID must be a string, got {type(attribute_id).__name__}.")

    attribute = ATTRIBUTE_PRESETS.get(attribute_id)
    if attribute is None:
        known = ", ".join(sorted(ATTRIBUTE_PRESETS))
        raise AttributeNotFoundError(
            f"Unknown attribute ID: '{attribute_id}'. Known IDs: {known}"
        )

    return attribute


__all__ = ["get_attribute", "list_attributes"]
