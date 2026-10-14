"""The change log gets names, teams and pushed ticks from git output alone (changelog_gen.py); git is mocked."""

import changelog_gen as cg


def _fake_git(*args):
    if args[0] == "rev-list":
        return "aaaaaaa1\nbbbbbbb2\n"
    return (
        "aaaaaaa1|2026-10-09|Add the notch pill\n"
        "bbbbbbb2|2026-10-10|WhatsApp: text me | when done\n"
        "ccccccc3|2026-10-13|Trader: a leak sweep before every push\n"
        "ddddddd4|2026-10-13|Something nobody planned for\n"
    )


def test_log_marks_only_remote_commits_as_pushed():
    commits = cg.read_log(run=_fake_git)
    assert [c["pushed"] for c in commits] == [True, True, False, False]
    assert commits[0]["hash"] == "aaaaaaa"


def test_teams_and_stable_names():
    rows = cg.build(cg.read_log(run=_fake_git))
    assert [r["team"] for r in rows] == [
        "WS7 Notch", "WS9 Phone, WhatsApp, Gmail", "WS1 Trading app", cg.DEFAULT_TEAM]
    assert [r["name"] for r in rows[:2]] == ["Alpha", "Beta"]
    assert "|" not in rows[1]["title"], "a pipe would break the table"


def test_names_stay_unique_past_the_pool():
    names = {cg.code_name(n) for n in range(1, len(cg.NAMES) * 2 + 1)}
    assert len(names) == len(cg.NAMES) * 2
    assert cg.code_name(len(cg.NAMES) + 1) == "Alpha II"


def test_override_pins_team_and_name():
    rows = cg.build(cg.read_log(run=_fake_git), {"ddddddd": {"team": "WS12 Design and motion", "name": "Stros"}})
    assert rows[3]["team"] == "WS12 Design and motion" and rows[3]["name"] == "Stros"


def test_render_has_ticks_summary_and_threads():
    rows = cg.build(cg.read_log(run=_fake_git))
    text = cg.render(rows, threads=[{"title": "Voice", "status": "working", "note": "still going"}], today="2026-10-14")
    assert "4 updates, 2 pushed" in text
    assert "✅" in text and "⬜" in text
    assert "Teams still working" in text and "still going" in text
    assert "## WS7 Notch" in text
