"""The curated skill list installs only what it names, skips what needs OK, and survives a bad file (skill_catalog.py)."""

import skill_catalog
import skill_packs
from skill_import import SkillImportError


def _fake_fetch(missing=()):
    """Stand-in for GitHub: every path returns a tiny SKILL.md, except the ones in ``missing``."""
    def fetch(url, raw=False):
        if not raw:
            return {"default_branch": "main"}
        if any(url.endswith(m) for m in missing):
            raise SkillImportError("Nothing there")
        name = url.rsplit("/", 2)[-2]
        return f"---\nname: {name}\ndescription: Test skill {name} for planning work\n---\n\n# {name}\nSteps.\n"
    return fetch


def test_installs_approved_packs_and_skips_needs_ok(tmp_path):
    result = skill_catalog.install(root=tmp_path, fetch=_fake_fetch())
    assert result["installed"]["claude-mem"] == 14
    assert "strix" not in result["installed"]
    assert any("strix" in p and "OK" in p for p in result["problems"])
    assert skill_packs.read("pack:claude-mem/make-plan", root=tmp_path).startswith("---")
    assert not list(tmp_path.rglob("*.py")), "scripts must never be copied"


def test_one_missing_file_does_not_stop_the_rest(tmp_path):
    result = skill_catalog.install(only=["ecc"], root=tmp_path,
                                   fetch=_fake_fetch(missing=("eval-harness/SKILL.md",)))
    assert result["installed"]["ecc"] == 6
    assert any("eval-harness" in p for p in result["problems"])


def test_plan_marks_needs_ok():
    rows = {r["pack"]: r for r in skill_catalog.plan()}
    assert rows["strix"]["skipped"] and not rows["agent-reach"]["skipped"]
    assert not {r["pack"]: r for r in skill_catalog.plan(include_needs_ok=True)}["strix"]["skipped"]
