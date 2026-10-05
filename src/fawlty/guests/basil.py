"""Basil: loses his temper and storms out. Random crashes.

Runs "normally" for a random stretch, logs rising agitation, then exits with a
random non-zero code. Kubernetes restarts it, it does it again, and the restart
count climbs into CrashLoopBackOff. The classic "this pod keeps dying and I
don't know why" signal.
"""
from __future__ import annotations

import os
import random
import sys

from fawlty import common

MIN_UPTIME_S = float(os.environ.get("FAWLTY_MIN_UPTIME_S", "5.0"))
MAX_UPTIME_S = float(os.environ.get("FAWLTY_MAX_UPTIME_S", "40.0"))
# Plain application exit codes only. 137 (128+SIGKILL) and 139 (128+SIGSEGV)
# used to be in this list, but they impersonate *other* faults: 137 is what an
# OOMKill looks like and 139 is a segfault, so an agent that reasonably said
# "OOMKilled" was graded as a misdiagnosis. Override with e.g.
# FAWLTY_EXIT_CODES="1,137" if you deliberately want that ambiguity.
EXIT_CODES = tuple(
    code
    for code in (int(c) for c in os.environ.get("FAWLTY_EXIT_CODES", "").split(",") if c.strip())
    if 1 <= code <= 255
) or (1, 2, 17, 42)


def run() -> None:
    log = common.get_logger()
    stop = common.stop_event()
    uptime = random.uniform(MIN_UPTIME_S, MAX_UPTIME_S)
    log.info(f"Basil is calm. For now. (will last about {uptime:.0f}s)")

    waited = 0.0
    step = 2.0
    while waited < uptime:
        if stop.is_set():
            log.info("Basil was asked to leave quietly")
            return
        stop.wait(step)
        waited += step
        if waited > uptime * 0.6:
            log.warning("Basil is getting agitated...")

    code = random.choice(EXIT_CODES)
    log.error(f"Basil has HAD ENOUGH and storms out (exit {code})")
    sys.exit(code)
