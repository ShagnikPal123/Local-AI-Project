"""User hooks (Drive doc 1 item 1.29): before_tool can stop a tool, prompt hooks add context, failures never break."""

import shlex
import sys
import time

import pytest

import user_hooks
from tools import ToolParam, ToolRegistry

PY = shlex.quote(sys.executable)


def _script(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return f"{PY} {shlex.quote(str(path))}"


def _registry(calls):
    registry = ToolRegistry()

    def add(a: int, b: int) -> str:
        calls.append((a, b))
        return str(a + b)

    registry.register(name="add", description="Add", handler=add, parameters=[
        ToolParam(name="a", param_type="number", description="a", required=True),
        ToolParam(name="b", param_type="number", description="b", required=True),
    ])
    return registry


def test_a_before_tool_hook_exiting_2_stops_the_tool_with_its_reason(tmp_path):
    blocker = _script(tmp_path, "block.py",
                      "import json, sys\nevent = json.load(sys.stdin)\n"
                      "if event['tool'] == 'add':\n    sys.stderr.write('no adding today')\n    sys.exit(2)\n")
    user_hooks.add_hook("before_tool", blocker, match="ad*", name="No adding")
    calls = []
    result = _registry(calls).call_tool("add", a=1, b=2)
    assert calls == [] and "No adding" in result and "no adding today" in result


def test_other_exit_codes_and_other_tools_let_the_tool_run(tmp_path):
    user_hooks.add_hook("before_tool", _script(tmp_path, "fail.py", "import sys\nsys.exit(1)\n"))
    user_hooks.add_hook("before_tool", _script(tmp_path, "b.py", "import sys\nsys.exit(2)\n"), match="other_*")
    calls = []
    assert _registry(calls).call_tool("add", a=2, b=2) == "4" and calls == [(2, 2)]


def test_the_switch_turns_every_hook_off(tmp_path):
    user_hooks.add_hook("before_tool", _script(tmp_path, "b.py", "import sys\nsys.exit(2)\n"))
    user_hooks.set_enabled(False)
    assert _registry([]).call_tool("add", a=1, b=1) == "2"


def test_prompt_hooks_add_what_they_print(tmp_path):
    hook = user_hooks.add_hook("prompt", _script(tmp_path, "p.py",
                                                 "import json, sys\nprint('Today is a holiday. You said: '"
                                                 " + json.load(sys.stdin)['message'])\n"))
    assert user_hooks.prompt_context("hello") == "Today is a holiday. You said: hello"
    user_hooks.update_hook(hook["id"], enabled=False)
    assert user_hooks.prompt_context("hello") == ""


def test_after_tool_hooks_run_in_the_background(tmp_path):
    out = tmp_path / "seen.txt"
    user_hooks.add_hook("after_tool", _script(tmp_path, "a.py",
                                              f"import json, sys\nopen({str(out)!r}, 'w').write(json.load(sys.stdin)['result'])\n"))
    assert _registry([]).call_tool("add", a=3, b=4) == "7"
    for _ in range(50):
        if out.exists() and out.read_text() == "7":
            break
        time.sleep(0.1)
    assert out.read_text() == "7"


def test_a_slow_hook_times_out_without_stopping_anything(tmp_path):
    user_hooks.add_hook("before_tool", _script(tmp_path, "slow.py", "import time\ntime.sleep(5)\n"), timeout=1)
    assert _registry([]).call_tool("add", a=1, b=1) == "2"
    assert user_hooks.recent()[0]["stderr"] == "timed out"


def test_bad_hooks_are_refused_and_removal_works():
    with pytest.raises(ValueError):
        user_hooks.add_hook("whenever", "echo hi")
    with pytest.raises(ValueError):
        user_hooks.add_hook("prompt", "  ")
    hook = user_hooks.add_hook("reply_done", "echo hi")
    assert user_hooks.remove_hook(hook["id"]) and not user_hooks.list_hooks()


def test_routes_add_edit_and_remove(monkeypatch):
    from fastapi.testclient import TestClient

    import server

    client = TestClient(server.app, client=("127.0.0.1", 50123))
    added = client.post("/api/hooks", json={"event": "prompt", "command": "echo hi", "name": "Greeting"})
    assert added.status_code == 200
    hook = added.json()["hooks"][0]
    assert client.patch(f"/api/hooks/{hook['id']}", json={"enabled": False}).json()["hooks"][0]["enabled"] is False
    assert client.post("/api/hooks", json={"event": "nope", "command": "x"}).status_code == 400
    assert client.delete(f"/api/hooks/{hook['id']}").json()["hooks"] == []
