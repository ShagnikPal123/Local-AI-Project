"""Lines affected and in which file, for every Code-tab and Improve edit (Request R9)."""

import difflib

import diff_stats


def _diff(before: str, after: str, path: str = "server.py", n: int = 3) -> str:
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                        fromfile=f"a/{path}", tofile=f"b/{path}", n=n))


BEFORE = "".join(f"line {i}\n" for i in range(1, 41))


def test_a_replacement_counts_each_line_once_and_names_the_file():
    after = BEFORE.replace("line 12\n", "LINE 12\n").replace("line 13\n", "LINE 13\nextra\n")
    summary = diff_stats.stats(_diff(BEFORE, after))
    [entry] = summary["files"]
    assert entry["path"] == "server.py"
    assert (entry["added"], entry["removed"], entry["affected"]) == (3, 2, 3)
    assert entry["ranges"] == [[12, 14]]
    assert diff_stats.describe(summary) == "server.py: 3 lines (+3 −2) at lines 12–14"


def test_separate_hunks_keep_separate_ranges():
    after = BEFORE.replace("line 2\n", "changed 2\n").replace("line 35\n", "")
    summary = diff_stats.from_texts(BEFORE, after, "providers/qwen_provider.py")
    [entry] = summary["files"]
    assert entry["ranges"] == [[2, 2], [34, 34]]
    assert entry["affected"] == 2
    assert "at lines 2, 34" in diff_stats.describe(summary)


def test_several_files_and_new_files():
    first = _diff(BEFORE, BEFORE.replace("line 5\n", "five\n"), "a.py")
    created = "".join(difflib.unified_diff([], ["x\n", "y\n"], fromfile="/dev/null", tofile="b/web/index.html", n=0))
    summary = diff_stats.stats(first + created)
    assert [f["path"] for f in summary["files"]] == ["a.py", "web/index.html"]
    assert summary["files"][1]["created"] and summary["files"][1]["added"] == 2
    text = diff_stats.describe(summary)
    assert text.startswith("2 files, 3 lines — a.py: 1 line (+1 −1) at line 5; new file web/index.html, 2 lines")


def test_nothing_changed_and_garbage_are_safe():
    assert diff_stats.stats("")["files"] == []
    assert diff_stats.describe_diff("not a diff at all") == "no lines changed"


def test_implement_change_reports_lines_while_working_and_when_applied():
    import improve_review

    class Result:
        ok = True
        error = ""
        file = relative = "improve_review.py"
        before = BEFORE
        after = BEFORE.replace("line 20\n", "twenty\n")
        diff = _diff(before, after, "improve_review.py")
        summary = "renamed"
        tests = ""

    class Log:
        def get(self, _id):
            return None

        def attach_review(self, *a):
            pass

        def record_content(self, *a):
            pass

        def publish(self, *a):
            pass

    steps = []
    outcome = improve_review.implement_change(
        {"id": "c1", "target": "improve_review.py", "title": "t", "description": "d"}, Log(), values={},
        model_fn=lambda *a, **k: "OK", preparer=lambda ch, **kw: Result(), committer=lambda r: r, on_step=steps.append)
    assert outcome["state"] == "applied"
    assert outcome["lines"]["files"][0]["path"] == "improve_review.py" and outcome["lines"]["affected"] == 1
    assert any("improve_review.py: 1 line (+1 −1) at line 20" in s for s in steps)
    assert "improve_review.py: 1 line" in outcome["message"]
