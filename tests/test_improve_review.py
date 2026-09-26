"""Improve tab review queue (Request J2/J3): duplicates, research, approve/deny, analyze all, implement."""

from __future__ import annotations

import json

import pytest

import improve_review as ir
from change_review import ChangeLog, ChangeOrigin


class Result:
    def __init__(self, ok=True, error=""):
        self.ok, self.error, self.diff, self.file, self.summary, self.seconds = ok, error, "--- a/x\n+++ b/x\n", "router.py", "did it", 1.0
        self.tests, self.already_failing = "3 passed", []


@pytest.fixture()
def world(tmp_path):
    log = ChangeLog(tmp_path / "changes.json")
    replies = {"idea": json.dumps({"verdict": "approve", "confidence": 0.8, "risk": "low", "already_done": False,
                                   "reasons": "router.py has no retry today."}),
               "critic": "OK\nFine.", "groups": json.dumps({"groups": []})}
    prompts, prepared, values = [], [], {"implement_approved": True, "test_depth": "quick", "max_patch_lines": 150}

    def model(prompt, system="", max_tokens=0):
        prompts.append(prompt)
        if "deciding whether an AI assistant should make" in prompt:
            return replies["idea"]
        if "reviewing a proposed change" in prompt:
            return replies["critic"]
        return replies["groups"]

    def preparer(change, **kw):
        prepared.append((change["id"], kw.get("feedback", "")))
        return world_result["value"]

    world_result = {"value": Result()}
    queue = ir.ReviewQueue(log=log, store=ir.ReviewStore(tmp_path / "reviews.json"), model_fn=model, preparer=preparer,
                           committer=lambda r: r, values_fn=lambda: values, threaded=False, web_fn=lambda q: "- a result")

    def propose(title, description="Retry timeouts with backoff.", target="router.py"):
        return log.propose(title=f"Improve {target}: {title}", description=description, author="Nyx (self-improvement)",
                           target=target, origin=ChangeOrigin.AGENT).change_id

    return {"q": queue, "log": log, "replies": replies, "prompts": prompts, "prepared": prepared, "values": values,
            "result": world_result, "propose": propose}


def test_reworded_repeats_are_grouped_without_a_model():
    a = {"id": "a", "target": "server.py", "status": "in_review", "created_at": 1,
         "title": "Improve server.py: Add robust shutdown task cancellation and timeout handling",
         "description": "Cancel background tasks on shutdown and await them with asyncio.wait_for and a timeout."}
    b = {**a, "id": "b", "created_at": 2, "title": "Improve server.py: Add timeout guards for shutdown tasks",
         "description": "Wrap shutdown task cancellation in asyncio.wait_for with a timeout so shutdown cannot hang."}
    c = {**a, "id": "c", "created_at": 3, "title": "Improve server.py: Cache the static bundle", "description": "Add immutable caching headers."}
    legacy = {**a, "id": "old", "created_at": 0, "status": "rejected", "reviewed_by": "Autopilot critic"}
    assert ir.group_duplicates([legacy, a, b, c]) == {"b": "a"}, "a refusal by the old broken critic is not a decision"


def test_owner_sentences_that_mean_the_queue():
    assert ir.review_intent("Apply all") == {"action": "analyze_apply"}
    assert ir.review_intent("Auto approve and auto apply these changes in review") == {"action": "analyze_apply"}
    assert ir.review_intent("deny the duplicates") == {"action": "deny_duplicates"}
    assert ir.review_intent("analyze everything in review") == {"action": "analyze"}
    assert ir.review_intent("Apply Image Generation and NSFW Request Handling")["action"] == "apply_matching"
    assert ir.review_intent("improve and auto approve all improvements for 22 hours") is None
    assert ir.review_intent("study for an hour") is None


def test_protected_files_are_denied_without_asking_a_model(world):
    change_id = world["propose"]("Log more", target="change_review.py")
    record = world["q"].research_and_recommend(world["log"].get(change_id).as_dict())
    assert record["verdict"] == "deny" and "protected" in record["reasons"] and world["prompts"] == []


def test_research_reads_the_file_and_the_web(world):
    change_id = world["propose"]("Retry provider timeouts", "Retry the provider stream when it times out.")
    record = world["q"].research_and_recommend(world["log"].get(change_id).as_dict(), web=True)
    assert record["verdict"] == "approve" and "Read router.py" in record["research"]
    assert "Outline:" in world["prompts"][0] and "Web research:" in world["prompts"][0]


def test_already_done_or_high_risk_is_never_approved():
    verdict = ir.parse_verdict(json.dumps({"verdict": "approve", "already_done": True, "risk": "low", "reasons": "x"}))
    assert verdict["verdict"] == "deny" and verdict["reasons"].startswith("Already done")
    assert ir.parse_verdict("not json at all, deny")["verdict"] is None, "no readable verdict is no recommendation"
    thinking = ("Here is a thinking process: I need to output {\"verdict\": ...} fields.\n"
                '{"verdict": "approve", "confidence": 0.7, "already_done": false, "risk": "low", "reasons": "No retry today."}')
    assert ir.parse_verdict(thinking)["verdict"] == "approve"


def test_approve_implements_through_the_critic_and_applies(world):
    change_id = world["propose"]("Retry provider timeouts")
    out = world["q"].approve(change_id)
    change = world["log"].get(change_id).as_dict()
    assert change["status"] == "published" and change["content"].startswith("--- a/x")
    assert out["implement"]["state"] == "applied"
    critic = next(p for p in world["prompts"] if "reviewing a proposed change" in p)
    assert "--- a/x" in critic, "the critic reads the real diff"
    assert change["reviewed_by"] == "Owner", "the approver stays the reviewer of record"


def test_implement_off_means_approve_only_and_it_is_visible(world):
    world["values"]["implement_approved"] = False
    change_id = world["propose"]("Retry provider timeouts")
    out = world["q"].approve(change_id)
    assert world["log"].get(change_id).status.value == "approved" and world["prepared"] == []
    assert out["implement"]["state"] == "approved_only"
    item = world["q"].queue()["items"][0]
    assert item["status"] == "approved" and item["implement"]["state"] == "approved_only"
    world["values"]["implement_approved"] = True
    assert world["q"].implement(change_id)["implement"]["state"] == "applied"


def test_blocked_diff_stays_approved_for_the_owner(world):
    world["replies"]["critic"] = "BLOCK\nDrops the lock."
    change_id = world["propose"]("Retry provider timeouts")
    out = world["q"].approve(change_id)
    assert out["implement"]["state"] == "blocked" and world["log"].get(change_id).status.value == "approved"


def test_failed_tests_retry_once_with_the_error(world):
    world["result"]["value"] = Result(ok=False, error="Edit 1's search text appears 0 times")
    change_id = world["propose"]("Retry provider timeouts")
    out = world["q"].approve(change_id)
    assert out["implement"]["state"] == "failed"
    assert world["prepared"] == [(change_id, ""), (change_id, "Edit 1's search text appears 0 times")]


def test_deny_and_deny_duplicates(world):
    first = world["propose"]("Retry provider timeouts on stream", "Retry the provider stream with backoff when it times out.")
    again = world["propose"]("Retry provider stream timeouts", "Retry the provider stream with backoff when it times out.")
    other = world["propose"]("Cache catalog", "Cache the model catalog for an hour.")
    assert world["q"].queue()["counts"]["duplicates"] == 1
    assert world["q"].deny_duplicates()["denied"] == 1
    assert world["log"].get(again).status.value == "rejected" and world["log"].get(first).status.value == "draft"
    world["q"].deny(other, reason="Not now")
    assert "Not now" in world["log"].get(other).ai_review


def test_analyze_all_then_apply_follows_the_recommendations(world):
    good = world["propose"]("Retry provider timeouts")
    world["propose"]("Retry provider timeouts again")
    protected = world["propose"]("Log more", target="auth.py")
    job = world["q"].analyze(then_apply=True)
    assert job["status"] == "done", job
    assert job["results"]["duplicates"] == 1 and job["results"]["applied"] == 1 and job["results"]["denied"] == 2
    assert world["log"].get(good).status.value == "published"
    assert world["log"].get(protected).status.value == "rejected"
    assert world["q"].queue()["counts"]["open"] == 0


def test_apply_with_explicit_decisions(world):
    a = world["propose"]("Retry provider timeouts")
    b = world["propose"]("Cache catalog", "Cache the model catalog for an hour.")
    job = world["q"].apply(decisions={a: "deny", b: "approve"}, implement=False)
    assert job["results"]["denied"] == 1 and job["results"]["approved"] == 1 and job["results"]["approved_only"] == 1
    assert world["log"].get(a).status.value == "rejected" and world["log"].get(b).status.value == "approved"


def test_model_grouping_catches_other_words(world):
    ids = [world["propose"](title, desc, target) for title, desc, target in [
        ("Timeout middleware", "Add a request timeout middleware.", "server.py"),
        ("Cancellation guards for endpoints", "Guard endpoints against cancellation leaks.", "server.py"),
        ("Progress events", "Stream progress events from tools.", "turn_runner.py"),
        ("Chunked streaming", "Send long answers in chunks.", "turn_runner.py"),
        ("Safety filter", "Check image prompts first.", "tools.py"),
        ("Intent capture", "Capture intent before writes.", "tools.py"),
    ]]
    world["replies"]["groups"] = json.dumps({"groups": [[1, 2], [3, 5]]})
    same = world["q"].cluster_same_ideas([world["log"].get(i).as_dict() for i in ids])
    assert same == {ids[1]: ids[0]}, "groups across different files are ignored"


def test_routes(world, monkeypatch):
    import server
    from fastapi.testclient import TestClient

    monkeypatch.setattr(ir, "REVIEW_QUEUE", world["q"])
    change_id = world["propose"]("Retry provider timeouts")
    local = TestClient(server.app, client=("127.0.0.1", 50081))
    body = local.get("/api/improve/review").json()
    assert body["counts"]["open"] == 1 and body["items"][0]["id"] == change_id
    assert local.post(f"/api/improve/changes/{change_id}/approve", json={"implement": False}).json()["status"] == "approved"
    typed = local.post("/api/improve/autopilot", json={"instruction": "Apply all"}).json()
    assert typed["intent"] == {"action": "analyze_apply"} and "Checking every open change" in typed["review"]["message"]
    remote = TestClient(server.app, client=("203.0.113.9", 50082))
    assert remote.get("/api/improve/review").status_code == 403
    assert remote.post(f"/api/improve/changes/{change_id}/deny", json={}).status_code == 403
