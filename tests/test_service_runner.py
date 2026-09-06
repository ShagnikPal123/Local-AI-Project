from service_runner import run_forever

def test_runner_restarts_after_transient_failure():
    calls = []
    def main():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("temporary")
    run_forever(main, lambda: len(calls) >= 2)
    assert len(calls) == 2
