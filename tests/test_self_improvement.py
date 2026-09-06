from self_improvement import ImprovementStore

def test_promotion_requires_owner_approval(tmp_path):
    store = ImprovementStore(str(tmp_path / "proposals.json"))
    proposal = store.propose("prompt", "test", {"text": "candidate"})
    try:
        store.promote(proposal.proposal_id, owner_approved=False)
    except PermissionError:
        pass
    else:
        raise AssertionError("promotion must require approval")
    promoted = store.promote(proposal.proposal_id, owner_approved=True)
    assert promoted.status == "live"
