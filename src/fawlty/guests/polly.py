"""Polly: screeches constantly. A high-volume log spammer.

Emits a flood of scary-looking but entirely benign ERROR/WARN lines at a high
rate, the way a misconfigured service drowns a logging backend. Nothing is
actually wrong; that is the point — it trains the ops layer to tell real
errors from noise.
"""
from __future__ import annotations

import itertools
import random

from fawlty import common

LINES_PER_SECOND = 50

SCARY_BUT_FINE = [
    "connection reset by peer (retrying, attempt %d)",
    "failed to acquire lock after %dms, backing off",
    "circuit breaker OPEN for upstream payments-svc",
    "deadline exceeded calling inventory-svc (%dms)",
    "dropped %d metrics: buffer full",
    "unexpected EOF reading response body",
    "token refresh failed, falling back to cached credentials",
    "GC pause %dms exceeded soft target",
    "retrying transaction after serialization failure",
    "slow query: SELECT took %dms",
]


def run() -> None:
    log = common.get_logger()
    stop = common.stop_event()
    log.info(f"Polly is warming up: ~{LINES_PER_SECOND} lines/s of pure noise")

    interval = 1.0 / LINES_PER_SECOND
    for i in itertools.count():
        if stop.is_set():
            break
        template = random.choice(SCARY_BUT_FINE)
        msg = template % random.randint(1, 5000) if "%d" in template else template
        # Mix levels so the record stream looks like a real degraded service.
        (log.error if i % 3 == 0 else log.warning)(f"{msg} [seq={i}]")
        stop.wait(interval)
