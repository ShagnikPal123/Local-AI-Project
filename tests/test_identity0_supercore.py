"""The constitution: the owner edits it, Big Kahuna can only propose, and every version can be rolled back."""

import pytest

from identity0 import supercore


def test_a_proposal_changes_nothing_until_the_owner_approves():
    before = supercore.current()
    proposal = supercore.propose({"voice": "Chatty."}, why="the owner seems to like longer answers")
    assert supercore.current()["voice"] == before["voice"]
    assert supercore.pending()[0]["id"] == proposal["id"]
    result = supercore.decide(proposal["id"], approve=True)
    assert result["current"]["voice"] == "Chatty." and "approved by owner" in result["current"]["by"]
    assert not supercore.pending()


def test_owner_edits_are_validated_and_can_be_rolled_back():
    supercore.update({"principles": ["Be kind."]})
    assert supercore.current()["principles"] == ["Be kind."]
    supercore.rollback()
    assert supercore.current()["principles"] == supercore.DEFAULT["principles"]
    with pytest.raises(supercore.ConstitutionError):
        supercore.update({"shadow_rate": 1})
    with pytest.raises(supercore.ConstitutionError):
        supercore.update({"principles": "not a list"})


def test_the_system_note_carries_persona_and_principles():
    note = supercore.system_note()
    assert "Big Kahuna" in note and "Never approve your own change" in note
