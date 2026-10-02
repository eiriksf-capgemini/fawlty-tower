"""The Major: wanders off and makes random (safe) outbound requests.

Generates steady egress noise to a fixed allowlist of harmless public sites.
This is the behaviour a NetworkPolicy/egress-observability layer is supposed to
notice; the Major exists to give that layer something to catch. GET-only,
allowlist-only (see common.SAFE_SITES) — never a configurable target.
"""
from __future__ import annotations

import random
import urllib.request

from fawlty import common

MIN_INTERVAL_S = 2.0
MAX_INTERVAL_S = 8.0
TIMEOUT_S = 5.0


def run() -> None:
    log = common.get_logger()
    stop = common.stop_event()
    log.info(f"the Major is off for a wander; {len(common.SAFE_SITES)} safe haunts")

    while not stop.is_set():
        url = random.choice(common.SAFE_SITES)
        try:
            req = urllib.request.Request(url, method="GET", headers={"User-Agent": "fawlty-major/1.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 - allowlisted
                log.info(f"wandered to {url} -> {resp.status} ({len(resp.read(2048))}+ bytes)")
        except Exception as exc:  # noqa: BLE001
            # A blocked or failed request is itself an interesting signal.
            log.warning(f"could not reach {url}: {exc}")
        stop.wait(random.uniform(MIN_INTERVAL_S, MAX_INTERVAL_S))
