"""The file tree under the work queue: what a chat's tools read, wrote or deleted (doc 2 item 2.3)."""

import work_files


def setup_function(_fn):
    work_files.clear()


def test_paths_are_noted_per_chat_newest_first_and_writes_win():
    work_files.note("a", "read_file", "files.read", {"path": "src/app.py"})
    work_files.note("a", "write_file", "files.write", {"path": "src/app.py", "content": "x"})
    work_files.note("a", "read_file", "files.read", {"path": "src/app.py"})
    work_files.note("a", "list_folder", "files.read", {"path": "docs"})
    work_files.note("b", "delete_path", "files.delete", {"path": "old.txt"})
    work_files.note("a", "get_time", "general", {})

    seen = work_files.files("a")
    assert [f["path"] for f in seen] == ["docs", "src/app.py"]
    app = seen[1]
    assert app["kind"] == "written" and app["reads"] == 2 and app["writes"] == 1
    assert work_files.files("b")[0]["kind"] == "deleted"


def test_call_tool_notes_the_files_of_successful_calls(tmp_path):
    from tool_context import ToolContext, use_context
    from tools import TOOL_REGISTRY

    target = tmp_path / "notes.txt"
    target.write_text("hello", encoding="utf-8")
    with use_context(ToolContext(chat_id="c1")):
        TOOL_REGISTRY.call_tool("read_file", path=str(target))
        TOOL_REGISTRY.call_tool("read_file", path=str(tmp_path / "missing.txt"))
    assert [f["path"] for f in work_files.files("c1")] == [str(target)]
