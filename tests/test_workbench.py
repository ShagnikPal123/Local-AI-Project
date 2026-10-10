"""The chat's workbench: files preview read-only, maths never evaluates raw code, graphs open as windows."""

import pytest

import routes_workbench as wb


def test_text_and_binary_files_preview(tmp_path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "b.bin").write_bytes(b"\x00\x01\x02")
    assert wb.preview_file(str(tmp_path / "a.txt"))["text"] == "hello"
    assert wb.preview_file(str(tmp_path / "b.bin"))["kind"] == "binary"
    with pytest.raises(FileNotFoundError):
        wb.preview_file(str(tmp_path / "missing.txt"))


@pytest.mark.parametrize("bad", ["__import__('os')", "open('x')", "x; y", "exec(x)", "lambda: 1", "x.__class__"])
def test_dangerous_expressions_are_refused(bad):
    with pytest.raises(ValueError):
        wb.check_expression(bad)


def test_sampling_leaves_gaps_outside_the_domain():
    curve = wb.sample(["ln(x)"], -1, 1, 21)[0]["ys"]
    assert curve[0] is None and curve[-1] == pytest.approx(0)


def test_symbolic_maths():
    assert wb.symbolic("derivative", "x^3")["result"] == "3*x**2"
    assert wb.symbolic("solve", "x^2 - 9 = 0")["result"] == "[-3, 3]"
    assert wb.symbolic("integral", "2*x")["result"] == "x**2"
    with pytest.raises(ValueError):
        wb.symbolic("teleport", "x")


def test_plot_tool_opens_a_graph_window(monkeypatch):
    sent = []
    import agent_events

    monkeypatch.setattr(agent_events, "publish_ui", lambda type, **p: sent.append((type, p)))
    assert "Opened a graph" in wb.tool_plot_function("sin(x); x^2/10", -5, 5)
    assert sent[-1][1]["kind"] == "graph" and sent[-1][1]["props"]["expressions"] == ["sin(x)", "x^2/10"]
    assert wb.tool_plot_function("os.system('x')").startswith("Error")
