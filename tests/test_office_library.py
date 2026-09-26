"""Office files and folders: the tree on disk is the tree in the lobby (Project Null N8).

The naming under test: an **office file** holds one office; a **folder** holds office files and other folders,
nested like Windows; a folder can link its work flows; nothing is ever destroyed, only moved to ``.trash``.
"""

import json
from pathlib import Path

import pytest

from office import library, memory, settings as settings_module
from office.state import Agent, Office, Section, Task, new_id


@pytest.fixture(autouse=True)
def root(tmp_path):
    library.use_root(tmp_path / "offices")
    yield tmp_path / "offices"
    library.use_root(None)


def test_a_new_office_is_a_folder_with_its_own_office_file(root):
    office, directory = library.create_office("Launch site")

    assert directory.name == "Launch site"
    assert (directory / "Launch site.office").exists(), "the office file carries the office's own name"
    assert (directory / "work").is_dir(), "agents need somewhere to put what they produce"
    assert json.loads((directory / "card.json").read_text(encoding="utf-8"))["id"] == office.id

    tree = library.tree()
    assert [o["name"] for o in tree["offices"]] == ["Launch site"]
    assert tree["offices"][0]["parent"] == ""


def test_folders_nest_and_offices_know_which_folder_they_are_in():
    outer = library.create_folder("Client work")
    inner = library.create_folder("Acme", outer["id"])
    office, _ = library.create_office("Site rebuild", inner["id"])

    tree = library.tree()
    folders = {f["name"]: f for f in tree["folders"]}
    assert folders["Acme"]["parent"] == outer["id"]
    assert tree["offices"][0]["parent"] == inner["id"]
    assert library.parent_folder_of(office.id).name == "Acme"


def test_dragging_an_office_into_a_folder_moves_it_on_disk():
    folder = library.create_folder("Ideas")
    office, directory = library.create_office("Loose office")

    library.move(office.id, folder["id"])

    assert not directory.exists()
    moved = library.find(office.id)
    assert moved.parent == folder["id"]
    assert Path(moved.path).parent.name == "Ideas"
    assert library.load(office.id).id == office.id, "it still opens after being moved"


def test_renaming_renames_the_folder_the_file_and_the_card():
    office, _ = library.create_office("Old name")

    library.rename(office.id, "New name")

    item = library.find(office.id)
    assert item.name == "New name"
    assert (Path(item.path) / "New name.office").exists()
    assert json.loads((Path(item.path) / "card.json").read_text(encoding="utf-8"))["name"] == "New name"
    assert library.load(office.id).name == "New name"


def test_link_work_flows_makes_the_offices_in_a_folder_siblings():
    folder = library.create_folder("One workflow")
    first, _ = library.create_office("Research", folder["id"])
    second, _ = library.create_office("Build", folder["id"])

    assert library.linked_siblings(first.id) == [], "a folder starts unlinked"

    library.set_linked(folder["id"], True)

    assert [s.name for s in library.linked_siblings(first.id)] == ["Build"]
    assert [s.name for s in library.linked_siblings(second.id)] == ["Research"]


def test_deleting_moves_to_trash_and_a_full_folder_refuses(root):
    folder = library.create_folder("Keep")
    office, _ = library.create_office("Done with this", folder["id"])

    with pytest.raises(library.LibraryError, match="still holds"):
        library.delete(folder["id"])

    result = library.delete(office.id)
    assert Path(result["trashed"]).exists(), "the owner's work is moved, never destroyed"
    assert library.find(office.id) is None
    library.delete(folder["id"])  # empty now


def test_names_windows_would_refuse_are_cleaned_and_kept_unique():
    assert library.clean_name('a/b:c*d?') == "a b c d"
    assert library.clean_name("   ") == "New office"
    assert library.clean_name("CON").lower().startswith("con (")

    first, _ = library.create_office("Same name")
    second, _ = library.create_office("Same name")
    assert {library.find(first.id).name, library.find(second.id).name} == {"Same name", "Same name (2)"}


def test_an_office_saves_and_reopens_with_its_team_but_nothing_still_running():
    office, directory = library.create_office("Memory test")
    section = Section(id=new_id("sec"), name="Frontend", color="#a594ff")
    office.sections[section.id] = section
    agent = Agent(id=new_id("agt"), name="Coder #1", role="coder", section_id=section.id, status="working",
                  step="Thinking", task_id="tsk-1")
    office.agents[agent.id] = agent
    task = Task(id=new_id("tsk"), title="Build it", section_id=section.id, agent_id=agent.id, status="working")
    office.tasks[task.id] = task
    library.save(office, directory)

    reopened = library.load(office.id)

    assert [s.name for s in reopened.sections.values()] == ["Frontend"]
    assert reopened.agents[agent.id].name == "Coder #1"
    assert reopened.agents[agent.id].status == "idle", "a run cannot survive the engine stopping"
    assert reopened.tasks[task.id].status == "queued", "unfinished work comes back as work to do"


def test_a_folder_made_in_explorer_shows_up_in_the_lobby(root):
    (root / "Made by hand").mkdir(parents=True)

    tree = library.tree()

    assert "Made by hand" in [f["name"] for f in tree["folders"]]
    assert all(f["id"] for f in tree["folders"]), "every folder gets an id the app can address it by"


def test_memory_survives_and_recall_prefers_what_matches():
    office, _ = library.create_office("Remembering")
    memory.add(office.id, "The owner wants the site in dark mode only.", kind="decision")
    memory.add(office.id, "Lunch is at noon.", kind="note")

    rows = memory.recall(office.id, "what did we decide about dark mode?")

    assert rows and rows[0]["text"].startswith("The owner wants the site in dark mode")
    assert "dark mode" in memory.brief(office.id, "dark mode")


def test_linked_folders_share_memory_in_recall():
    folder = library.create_folder("Linked")
    first, _ = library.create_office("Design", folder["id"])
    second, _ = library.create_office("Build", folder["id"])
    memory.add(first.id, "The palette is black with a purple accent.", kind="fact")
    library.set_linked(folder["id"], True)

    rows = memory.recall(second.id, "which palette are we using?")

    assert rows and rows[0]["from"] == "Design"
    assert "Design" in memory.linked_note(second.id)


def test_settings_live_next_to_the_library_and_only_take_known_values(root):
    assert settings_module.load()["focus_mode"] == "ask"

    saved = settings_module.save({"focus_mode": "nonsense", "allow_web": False, "max_agents": 25, "junk": 1})

    assert saved["focus_mode"] == "ask", "an unknown choice leaves the setting alone"
    assert saved["allow_web"] is False and saved["max_agents"] == 25
    assert "junk" not in saved
    assert (root / ".settings.json").exists()
    assert "Made by hand" not in [f["name"] for f in library.tree()["folders"]], "dot-files are not offices"
