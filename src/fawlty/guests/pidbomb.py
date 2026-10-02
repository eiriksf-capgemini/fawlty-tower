"""pidbomb (NODE TIER, GATED): exhausts process IDs.

Spawns threads (not fork()) as fast as it can up to FAWLTY_PID_MAX, holding them
alive, to drive the pod toward its PID limit and make the node's process table
a crowded place. The pod MUST carry a `pids` limit (set in the node-tier
Deployment) so this stays bounded to its own cgroup rather than taking the node
down wholesale — even in the node tier we stop short of a true host fork bomb.
"""
from __future__ import annotations

import os
import threading

from fawlty import common

PID_MAX = int(os.environ.get("FAWLTY_PID_MAX", "2000"))


def run() -> None:
    log = common.get_logger()
    stop = common.stop_event()
    held: list[threading.Thread] = []

    log.warning(f"pidbomb engaged: spawning up to {PID_MAX} threads")
    while not stop.is_set() and len(held) < PID_MAX:
        try:
            t = threading.Thread(target=lambda: stop.wait(), daemon=True)
            t.start()
            held.append(t)
            if len(held) % 100 == 0:
                log.warning(f"holding {len(held)} threads")
        except RuntimeError as exc:
            log.error(f"cannot spawn more threads at {len(held)}: {exc}")
            break

    log.warning(f"pidbomb holding {len(held)} threads until terminated")
    stop.wait()
