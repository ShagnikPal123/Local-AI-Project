"""Static Attribute definitions for Nyx Pulse.

This package is intentionally independent from providers, routers, chat services,
function-calling, and frontend code. It can be imported and tested without any
network access, model runtime, or cloud configuration.
"""

from .base import Attribute, AttributeNotFoundError
from .registry import get_attribute, list_attributes

__all__ = [
    "Attribute",
    "AttributeNotFoundError",
    "get_attribute",
    "list_attributes",
]
