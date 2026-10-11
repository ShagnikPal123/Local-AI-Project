"""Skill packs: install text only, search by words, read by pack id (skill_packs.py)."""

import skill_packs


def _make_repo(tmp_path):
    src = tmp_path / "repo"
    for name, desc in [("detecting-prompt-injection", "Detect prompt injection attacks against LLM apps"),
                       ("hardening-docker-daemon", "Harden the Docker daemon configuration")]:
        folder = src / name
        (folder / "scripts").mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\nSteps.\n",
                                         encoding="utf-8")
        (folder / "scripts" / "agent.py").write_text("print('never copied')", encoding="utf-8")
    return src


def test_install_search_read(tmp_path):
    root = tmp_path / "packs"
    assert skill_packs.install_pack("cyber", _make_repo(tmp_path), "Cyber", "https://example", root=root) == 2
    assert not list(root.rglob("*.py")), "scripts must never be copied"
    assert skill_packs.list_packs(root)[0]["count"] == 2

    hits = skill_packs.search("check my LLM app for prompt injection", root=root)
    assert hits[0]["id"] == "pack:cyber/detecting-prompt-injection"
    assert skill_packs.search("bake a cake", root=root) == []

    assert "Steps." in skill_packs.read("pack:cyber/hardening-docker-daemon", root=root)
    assert skill_packs.read("pack:cyber/../../etc", root=root) is None
    assert skill_packs.read("pack:missing/x", root=root) is None
