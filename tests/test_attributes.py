"""Offline tests for the standalone Attributes package."""

from dataclasses import FrozenInstanceError

import pytest

from attributes import Attribute, AttributeNotFoundError, get_attribute, list_attributes


def test_list_attributes_returns_all_expected_attribute_ids():
    """The registry should expose the starter attributes plus finance."""
    attributes = list_attributes()
    ids = [item.id for item in attributes]

    assert ids == [
        "coding",
        "web_development",
        "app_development",
        "debugging",
        "explain",
        "auto_model",
        "finance",
    ]


def test_each_item_is_an_attribute_instance():
    """Each element in the registry should be a typed Attribute object."""
    attributes = list_attributes()
    assert all(isinstance(item, Attribute) for item in attributes)


def test_get_attribute_coding_returns_coding_attribute():
    """A known ID should return the matching static attribute."""
    attribute = get_attribute("coding")

    assert attribute.id == "coding"
    assert attribute.display_name == "Coding"
    assert attribute.preferred_task_type == "coding"


def test_get_attribute_auto_model_has_non_binding_auto_hint():
    """Auto-model attribute should be a metadata hint only and not a routing engine."""
    attribute = get_attribute("auto_model")

    assert attribute.preferred_task_type == "auto"
    assert attribute.response_style == "balanced"
    assert "routing logic" in attribute.system_guidance.lower()


def test_unknown_id_raises_attribute_not_found_error():
    """Unknown IDs should fail loudly, not silently fallback."""
    with pytest.raises(AttributeNotFoundError, match="Unknown attribute ID"):
        get_attribute("does_not_exist")


def test_attributes_have_non_empty_required_fields():
    """All required fields must be populated."""
    for attribute in list_attributes():
        assert attribute.id
        assert attribute.display_name
        assert attribute.description
        assert attribute.system_guidance


def test_registry_is_independent_of_router_or_provider_code():
    """Attributes must not import provider, router, or service code in a clean import."""
    import subprocess
    import sys

    code = """
import attributes
print('attributes_ok')
print('router' in __import__('sys').modules)
print('providers' in __import__('sys').modules)
print('chat_service' in __import__('sys').modules)
print('fastapi' in __import__('sys').modules)
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=".",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "attributes_ok"
    assert lines[1] == "False"
    assert lines[2] == "False"
    assert lines[3] == "False"
    assert lines[4] == "False"


def test_attribute_object_is_immutable():
    """The dataclass should behave as an immutable value object."""
    attribute = get_attribute("coding")

    with pytest.raises(FrozenInstanceError):
        attribute.id = "changed"
