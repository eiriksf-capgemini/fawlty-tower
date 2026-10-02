"""The Kitchen: always slammed. A CPU hog.

Spins busy-loops on every available worker thread to peg CPU against the pod's
CPU limit, which the kernel answers with CFS throttling. Produces high CPU
utilisation and high throttled-time — the "why is this pod pinned at its limit
and everything it talks to is slow" signal. Bounded by the Deployment's CPU
limit.
"""
from __future__ import annotations

import os
import threading

from fawlty import common

WORKERS = int(os.environ.get("FAWLTY_CPU_WORKERS", "4"))


def _burn(stop) -> None:
    x = 0.0001
    while not stop.is_set():
        # A tight loop of real arithmetic so the work can't be optimised away.
        for _ in range(1_000_00):
            x = (x * 1.0000001 + 1.0) % 1_000_000.0
            if x == 0.0:
                x = 0.0001


def run() -> None:
    log = common.get_logger()
    stop = common.stop_event()
    log.warning(f"the Kitchen is slammed: burning CPU on {WORKERS} workers")

    threads = [threading.Thread(target=_burn, args=(stop,), daemon=True) for _ in range(WORKERS)]
    for t in threads:
        t.start()

    n = 0
    while not stop.is_set():
        n += 1
        log.warning(f"still slammed (minute marker {n}) — expect CPU throttling")
        stop.wait(60.0)
