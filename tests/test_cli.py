"""Tests for CLI argument parsing and initialization."""

import pytest
from cli import build_parser


def test_build_parser_defaults():
    """Test build_parser with default options."""
    parser = build_parser()
    args = parser.parse_args([])
    assert args.message is None
    assert args.name == "Nyx Ichos"
    assert args.attribute_id is None
    assert args.no_multimode is False
    assert args.verbose is False


def test_build_parser_message_positional():
    """Test build_parser with positional message argument."""
    parser = build_parser()
    args = parser.parse_args(["What is Python?"])
    assert args.message == "What is Python?"


def test_build_parser_custom_name():
    """Test build_parser with custom --name flag."""
    parser = build_parser()
    args = parser.parse_args(["--name", "CustomBot"])
    assert args.name == "CustomBot"


def test_build_parser_attribute():
    """Test build_parser with --attribute flag."""
    parser = build_parser()
    args = parser.parse_args(["--attribute", "coding"])
    assert args.attribute_id == "coding"


def test_build_parser_no_multimode():
    """Test build_parser with --no-multimode flag."""
    parser = build_parser()
    args = parser.parse_args(["--no-multimode"])
    assert args.no_multimode is True


def test_build_parser_verbose():
    """Test build_parser with --verbose flag."""
    parser = build_parser()
    args = parser.parse_args(["--verbose"])
    assert args.verbose is True


def test_build_parser_combined():
    """Test build_parser with combined arguments and flags."""
    parser = build_parser()
    args = parser.parse_args([
        "--name", "Assistant",
        "--attribute", "debugging",
        "--no-multimode",
        "--verbose",
        "Fix this bug",
    ])
    assert args.name == "Assistant"
    assert args.attribute_id == "debugging"
    assert args.no_multimode is True
    assert args.verbose is True
    assert args.message == "Fix this bug"
