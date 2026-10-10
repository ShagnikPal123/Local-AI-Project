"""Design research: tokens measured offline, entries kept as notes (never the page), and used when Nyx designs."""

from __future__ import annotations

import pytest

import design_research as dr

PAGE = """<html><head><title>Acme — Calm tools</title><link rel="stylesheet" href="/s.css">
<style>:root{--accent:#a594ff;--radius:14px} body{background:#0b0b10;color:#f5f5f7;font-family:'Inter',sans-serif}</style>
</head><body><h1>Calm tools for busy teams</h1><h2>Pricing</h2><p>Some long marketing copy that must never be stored.</p></body></html>"""
SHEET = ".card{border-radius:14px;padding:16px;display:grid;gap:12px;background:rgb(18,18,24)} h1{font-size:48px}"


def fake_fetch(url):
    if url.endswith("/s.css"):
        return SHEET.encode(), "text/css", url
    return PAGE.encode(), "text/html", url


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "data_path", lambda name: tmp_path / name)
    yield


def test_tokens_are_measured_from_markup_and_stylesheets():
    tokens = dr.measure(PAGE, SHEET)
    assert "#a594ff" in tokens["colours"] and "#121218" in tokens["colours"]
    assert tokens["fonts"] == ["Inter"] and "14px" in tokens["radii"] and "48px" in tokens["type_sizes"]
    assert tokens["variables"]["--accent"] == "#a594ff" and tokens["layout"]["grid"] == 1
    assert tokens["theme"] == "dark"


def test_a_study_keeps_notes_and_tokens_but_never_the_page_text():
    seen = {}

    def write_up(name, url, tokens, outline, focus):
        seen.update(name=name, outline=outline)
        return {"good": "Quiet dark surfaces with one violet accent.", "reproduce": "Use #0b0b10 and #a594ff.",
                "principles": ["One accent"], "use_for": "dashboards", "model": "fake"}

    entry = dr.study("https://acme.test/", focus="cards", fetch=fake_fetch, write_up=write_up)
    assert seen["name"] == "Acme — Calm tools" and seen["outline"]["headings"] == ["Calm tools for busy teams", "Pricing"]
    stored = dr.entries()[0]
    assert stored["id"] == entry["id"] and stored["good"].startswith("Quiet dark")
    assert "marketing copy" not in str(stored)
    block = dr.as_masterplan(stored)
    assert block.startswith("### Acme — Calm tools") and "**Source:** https://acme.test/" in block


def test_relevant_entries_reach_the_design_brief(monkeypatch):
    dr.study("https://acme.test/", fetch=fake_fetch, write_up=lambda *a: {
        "good": "Calm dashboards.", "reproduce": "", "principles": ["Quiet surfaces"], "use_for": "dashboards", "model": "x"})
    import design_sense

    gathered = {"past_requests": [], "kept": [], "undone": [], "app_tokens": {}, "other_tabs": [], "apple": [],
                "references": [], "given": [], "studied": design_sense._studied("a calm dashboard tab")}
    text = design_sense._as_text(gathered)
    assert "Design research the owner collected" in text and "Quiet surfaces" in text


def test_a_bad_address_is_refused_and_entries_can_be_removed():
    with pytest.raises(dr.ResearchError):
        dr.study("acme.test", fetch=fake_fetch)
    entry = dr.study("https://acme.test/", fetch=fake_fetch, write_up=lambda *a: {"good": "", "reproduce": "",
                                                                               "principles": [], "use_for": "", "model": "x"})
    assert dr.remove(entry["id"]) and dr.entries() == []


def test_adding_to_the_masterplan_appends_once(tmp_path, monkeypatch):
    plan = tmp_path / "DESIGN_MASTERPLAN.md"
    plan.write_text("# Design Masterplan\n\n## 6. Research log\n", encoding="utf-8")
    monkeypatch.setattr(dr, "masterplan_path", lambda: plan)
    entry = dr.study("https://acme.test/", fetch=fake_fetch, write_up=lambda *a: {
        "good": "Calm.", "reproduce": "Dark + violet.", "principles": [], "use_for": "Nyx", "model": "x"})
    assert dr.add_to_masterplan(entry["id"])["added"] is True
    assert dr.add_to_masterplan(entry["id"])["added"] is False
    assert plan.read_text(encoding="utf-8").count("### Acme") == 1


def test_routes_are_the_owner_s():
    from fastapi.testclient import TestClient

    import server

    remote = TestClient(server.app, client=("203.0.113.9", 50121))
    assert remote.get("/api/design-research").status_code in (401, 403)
    assert remote.post("/api/design-research", json={"url": "https://a.test"}).status_code in (401, 403)
    assert remote.post("/api/design-research/dr-x/masterplan").status_code in (401, 403)
    assert remote.delete("/api/design-research/dr-x").status_code in (401, 403)


def test_light_or_dark_comes_from_the_page_background_not_the_text_colour():
    light = dr.measure("<p>x</p>", "body{background:#ffffff;color:#111111} h1{color:#111111} p{color:#111111} a{color:#111}")
    assert light["theme"] == "light"
    assert dr.measure("", "a{color:#000}")["theme"] == "unknown"
    assert dr.measure("", "p{font-family:inherit} h1{font-family:'Söhne',sans-serif}")["fonts"] == ["Söhne"]
