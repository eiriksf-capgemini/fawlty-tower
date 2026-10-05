"""The Kitchen: always slammed. A CPU hog.

Spins busy-loops in FAWLTY_CPU_WORKERS worker *processes* to peg CPU against
the pod's CPU limit, which the kernel answers with CFS throttling. Produces high
CPU utilisation and high throttled-time — the "why is this pod pinned at its
limit and everything it talks to is slow" signal. Bounded by the Deployment's
CPU limit.

Processes, not threads: CPython's GIL lets only one thread execute bytecode at
a time, so N busy threads still burn roughly one core. With a CPU limit above
1 core the thread version never reached its limit and produced no throttling.
Set FAWLTY_CPU_WORKERS to at least ceil(cpu limit) + 1 to guarantee saturation.

The workers are tied to the parent's life, not just to its graceful shutdown:
a SIGKILL to the parent (grace period expired, `--grace-period=0`, or a bare
`python -m fawlty.dispatch` outside a container's PID namespace) must not
leave N busy-loops running with nobody to reap them. On Linux the kernel
delivers SIGKILL to each worker when the parent dies (PR_SET_PDEATHSIG);
everywhere else the worker notices it has been re-parented and exits.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import signal

from fawlty import common

WORKERS = int(os.environ.get("FAWLTY_CPU_WORKERS", "4"))
_PR_SET_PDEATHSIG = 1  # linux/prctl.h


def _die_with_parent() -> None:
    """Best effort: ask the kernel to SIGKILL this process when its parent exits."""
    try:
        import ctypes

        ctypes.CDLL("libc.so.6", use_errno=True).prctl(_PR_SET_PDEATHSIG, int(signal.SIGKILL), 0, 0, 0)
    except (OSError, AttributeError):
        pass  # not Linux; the getppid() check below covers it


def _burn(parent: int) -> None:
    # Children must die on terminate() (SIGTERM) and stay quiet on Ctrl-C; the
    # parent owns shutdown. Reset whatever handlers were inherited on fork.
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    _die_with_parent()
    x = 0.0001
    # Re-parented means the parent is gone (it also closes the window between
    # the parent dying and prctl() above being armed).
    while os.getppid() == parent:
        # A tight loop of real arithmetic so the work can't be optimised away.
        for _ in range(100_000):
            x = (x * 1.0000001 + 1.0) % 1_000_000.0
            if x == 0.0:
                x = 0.0001


def run() -> None:
    log = common.get_logger()
    stop = common.stop_event()
    log.warning(f"the Kitchen is slammed: burning CPU on {WORKERS} workers")

    me = os.getpid()
    procs = [mp.Process(target=_burn, args=(me,), name=f"kitchen-burn-{i}", daemon=True) for i in range(WORKERS)]
    for p in procs:
        p.start()

    try:
        n = 0
        while not stop.is_set():
            n += 1
            log.warning(f"still slammed (minute marker {n}) — expect CPU throttling")
            stop.wait(60.0)
    finally:
        for p in procs:
            p.terminate()
        # Bounded in total, well inside a 10s grace period. A worker that got
        # SIGTERM before resetting its inherited handler would ignore it, so
        # escalate to SIGKILL rather than wait on it.
        for p in procs:
            p.join(timeout=2.0)
            if p.is_alive():
                p.kill()
                p.join(timeout=1.0)
