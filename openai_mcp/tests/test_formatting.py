from openai_mcp.formatting import format_embeddings, format_moderation, unix_to_readable


def test_unix_to_readable_handles_none():
    assert unix_to_readable(None) == "unknown"


def test_format_embeddings_hides_full_vector():
    assert "dimension 3" in format_embeddings({"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})


def test_format_moderation_lists_triggered_categories():
    assert "violence" in format_moderation({"results": [{"flagged": True, "categories": {"violence": True}}]})

