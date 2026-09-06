'''Resilient 24/7 runner with bounded restart backoff.'''
import logging
import time
from collections.abc import Callable

def run_forever(main: Callable[[], None], stop_requested: Callable[[], bool], max_backoff: float = 60.0) -> None:
    backoff = 1.0
    while not stop_requested():
        try:
            main()
            backoff = 1.0
        except KeyboardInterrupt:
            return
        except Exception:
            logging.exception("Assistant stopped unexpectedly; restarting safely")
            time.sleep(backoff)
            backoff = min(max_backoff, backoff * 2)
