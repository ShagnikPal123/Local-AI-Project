"""Question cards: an image drop box needs no options; a plain card still needs two (doc 1, item 1.19)."""

import question_cards


def test_image_card_needs_no_options():
    card = question_cards.parse('{"question": "Send me a screenshot of the error", "kind": "image"}')
    assert card is not None
    assert card["kind"] == "image"
    assert card["options"] == []
    assert card["other"] == "Or describe it in words"


def test_plain_card_still_needs_two_options():
    assert question_cards.parse('{"question": "Pick one", "options": ["only"]}') is None


def test_multi_card_keeps_multi():
    card = question_cards.parse('{"question": "Which?", "options": ["a", "b", "c"], "multi": true}')
    assert card and card["multi"] is True and "kind" not in card


def test_format_rule_mentions_checkboxes_and_drop_box():
    assert "checkboxes" in question_cards.FORMAT_RULE
    assert '"kind": "image"' in question_cards.FORMAT_RULE
