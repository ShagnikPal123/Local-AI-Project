"""Templates: every one is valid data, files land only inside the chosen folder, nothing is overwritten."""

import pytest

from identity0 import templates
from identity0.templates.catalog import TEMPLATES


def test_the_catalog_is_broad_and_ids_are_unique():
    ids = [t["id"] for t in TEMPLATES]
    assert len(ids) == len(set(ids)) and len(ids) >= 60
    assert {"Code", "Websites", "DevOps", "Documents", "Tabs", "Prompts"} <= set(templates.categories())


def test_every_tab_template_is_a_valid_tab_spec():
    from dynamic_tabs import build_spec

    for t in TEMPLATES:
        if t["kind"] == "tab":
            spec = t["spec"]
            build_spec(label=spec["label"], blocks=spec["blocks"], icon=spec["icon"], description=spec["description"])


def test_search_finds_the_obvious_template():
    assert templates.search("portfolio website")[0]["id"] == "portfolio"
    assert templates.best_for("make me a react app")["id"] == "react-vite-ts"
    assert templates.search("", category="Prompts")


@pytest.mark.parametrize("template_id", [t["id"] for t in TEMPLATES if t["kind"] == "files"])
def test_every_files_template_writes_only_inside_its_folder(tmp_path, template_id):
    work = tmp_path / "work"  # the shared fixture keeps its own files in tmp_path
    work.mkdir()
    result = templates.instantiate(template_id, folder=str(work), name="demo app")
    root = work / ("demo_app" if "python" in templates.get(template_id)["tags"] else "demo-app")
    assert result["folder"] == str(root.resolve())
    written = [p for p in work.rglob("*") if p.is_file()]
    assert written and all(root.resolve() in p.resolve().parents for p in written)
    assert not any("{{name}}" in p.read_text(encoding="utf-8") for p in written)


def test_existing_folders_are_never_overwritten_and_bad_folders_refused(tmp_path):
    templates.instantiate("landing-page", folder=str(tmp_path), name="site")
    with pytest.raises(templates.TemplateError):
        templates.instantiate("landing-page", folder=str(tmp_path), name="site")
    with pytest.raises(templates.TemplateError):
        templates.instantiate("landing-page", folder="relative/path", name="x")
    with pytest.raises(templates.TemplateError):
        templates.instantiate("landing-page", folder=str(tmp_path), name="../escape")


def test_documents_come_back_as_text_and_tabs_become_real_tabs(tmp_path, monkeypatch):
    assert "Decision" in templates.instantiate("adr", name="Use Big Kahuna")["text"]
    import dynamic_tabs

    monkeypatch.setattr(dynamic_tabs, "TAB_STORE", dynamic_tabs.TabStore(tmp_path / "tabs.json"))
    made = templates.instantiate("tab-habit-tracker")
    assert made["kind"] == "tab" and made["label"] == "Habits"
