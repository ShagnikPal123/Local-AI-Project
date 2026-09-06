from approaches import try_approaches

def test_approach_retry_after_failure():
    seen = []
    def solve(prompt):
        seen.append(prompt)
        if len(seen) == 1:
            raise RuntimeError("failed")
        return "worked"
    result, approach = try_approaches("task", solve, ["direct", "systems"])
    assert result == "worked"
    assert approach == "systems"
