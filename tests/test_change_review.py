"""Change proposal, review, and publication (ROADMAP AA7-AA11, F7).

The property that matters most: nothing can reach users without passing through
review. That is the gate that makes agent self-modification safe to leave on, so
most of these tests try to get around it.
"""

import pytest

from change_review import ChangeError, ChangeLog, ChangeOrigin, ChangeStatus, build_review_prompt


@pytest.fixture
def log(tmp_path):
    return ChangeLog(tmp_path / "changes.json")


def _propose(log, title="Add a thing", target="settings", origin=ChangeOrigin.HUMAN):
    return log.propose(
        title=title,
        description="does a thing",
        author="shagnikpal@gmail.com",
        target=target,
        content="new content",
        previous_content="old content",
        origin=origin,
    )


# --- proposal ---------------------------------------------------------------------

def test_a_change_starts_as_a_draft(log):
    assert _propose(log).status is ChangeStatus.DRAFT


def test_a_change_needs_a_title(log):
    with pytest.raises(ChangeError):
        log.propose(title="  ", description="", author="a", target="settings")


def test_a_change_needs_a_target(log):
    with pytest.raises(ChangeError):
        log.propose(title="Something", description="", author="a", target="  ")


def test_the_previous_state_is_kept_for_rollback(log):
    assert _propose(log).previous_content == "old content"


# --- the review gate ----------------------------------------------------------------

def test_a_draft_cannot_be_published_directly(log):
    """The gate that makes self-modification safe to leave switched on."""
    change = _propose(log)
    with pytest.raises(ChangeError):
        log.publish(change.change_id, "shagnikpal@gmail.com")


def test_a_draft_cannot_be_approved_without_review(log):
    change = _propose(log)
    with pytest.raises(ChangeError):
        log.approve(change.change_id, "shagnikpal@gmail.com")


def test_an_agent_change_gets_the_same_gate_as_a_human_one(log):
    change = _propose(log, origin=ChangeOrigin.AGENT)
    with pytest.raises(ChangeError):
        log.publish(change.change_id, "shagnikpal@gmail.com")


def test_the_happy_path_reaches_published(log):
    change = _propose(log)
    log.submit_for_review(change.change_id)
    log.approve(change.change_id, "reviewer@example.com")
    published = log.publish(change.change_id, "shagnikpal@gmail.com")
    assert published.status is ChangeStatus.PUBLISHED
    assert published.published_by == "shagnikpal@gmail.com"
    assert published.published_at is not None


def test_a_rejected_change_is_a_dead_end(log):
    change = _propose(log)
    log.reject(change.change_id, "reviewer@example.com", "not safe")

    with pytest.raises(ChangeError):
        log.submit_for_review(change.change_id)
    with pytest.raises(ChangeError):
        log.approve(change.change_id, "reviewer@example.com")
    with pytest.raises(ChangeError):
        log.publish(change.change_id, "shagnikpal@gmail.com")


def test_a_published_change_cannot_be_published_twice(log):
    change = _propose(log)
    log.submit_for_review(change.change_id)
    log.approve(change.change_id, "r@example.com")
    log.publish(change.change_id, "o@example.com")
    with pytest.raises(ChangeError):
        log.publish(change.change_id, "o@example.com")


def test_an_unknown_change_cannot_be_transitioned(log):
    with pytest.raises(ChangeError):
        log.submit_for_review("nope")


# --- review is notes, not a verdict --------------------------------------------------

def test_attaching_a_review_does_not_approve_anything(log):
    """Collapsing review and approval would let an AI approve its own change."""
    change = _propose(log)
    log.submit_for_review(change.change_id)
    reviewed = log.attach_review(change.change_id, "looks risky", "ai")
    assert reviewed.status is ChangeStatus.IN_REVIEW
    assert reviewed.ai_review == "looks risky"


def test_the_review_prompt_asks_for_problems_not_a_verdict(log):
    """A reviewer prompted to approve will approve."""
    prompt = build_review_prompt(_propose(log))
    assert "problems" in prompt.lower()
    assert "do not approve or reject" in prompt.lower()


def test_the_review_prompt_names_the_origin(log):
    prompt = build_review_prompt(_propose(log, origin=ChangeOrigin.AGENT))
    assert "agent" in prompt


# --- rollback -------------------------------------------------------------------------

def test_a_published_change_can_be_rolled_back_to_its_previous_state(log):
    change = _propose(log)
    log.submit_for_review(change.change_id)
    log.approve(change.change_id, "r@example.com")
    log.publish(change.change_id, "o@example.com")
    rolled = log.rollback(change.change_id, "o@example.com")
    assert rolled.status is ChangeStatus.ROLLED_BACK
    assert rolled.content == "old content"


def test_an_unpublished_change_cannot_be_rolled_back(log):
    change = _propose(log)
    with pytest.raises(ChangeError):
        log.rollback(change.change_id, "o@example.com")


# --- listing and persistence ----------------------------------------------------------

def test_changes_can_be_filtered_by_status(log):
    _propose(log, title="one")
    second = _propose(log, title="two")
    log.submit_for_review(second.change_id)
    drafts = log.list_changes(ChangeStatus.DRAFT)
    assert [c["title"] for c in drafts] == ["one"]


def test_the_summary_counts_what_needs_attention(log):
    first = _propose(log, title="one")
    log.submit_for_review(first.change_id)
    second = _propose(log, title="two")
    log.submit_for_review(second.change_id)
    log.approve(second.change_id, "r@example.com")

    summary = log.summary()
    assert summary["awaiting_review"] == 1
    assert summary["ready_to_publish"] == 1


def test_history_survives_a_restart(tmp_path):
    path = tmp_path / "changes.json"
    first = ChangeLog(path)
    change = first.propose("Persisted", "", "a@example.com", "settings", "c", "p")

    second = ChangeLog(path)
    assert second.get(change.change_id) is not None


def test_a_corrupt_history_file_does_not_crash(tmp_path):
    path = tmp_path / "changes.json"
    path.write_text("{ not json", encoding="utf-8")
    assert ChangeLog(path).list_changes() == []


# --- a bad target is refused where it is written, not at publish time ------------------

@pytest.mark.parametrize("target", ["../server.py", "..\\auth.py", "some/path"])
def test_a_path_escaping_target_is_refused_at_proposal(log, target):
    """It must not sit in the review queue looking approvable."""
    with pytest.raises(ChangeError):
        log.propose(title="Escape", description="", author="a@example.com", target=target)
