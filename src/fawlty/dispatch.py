"""Entry point: pick a guest by FAWLTY_GUEST and run it.

    python -m fawlty.dispatch

Every Deployment in the fawlty-tower workload uses the SAME image and differs
only by the FAWLTY_GUEST env var. That keeps the build to a single image and
makes adding a fault a one-file change.
"""
from __future__ import annotations

import importlib
import sys

from fawlty import common

# Map guest name -> module under fawlty.guests. Keep this list in sync with your
# Deployment manifests and the `fawlty` CLI's roster.
GUESTS: dict[str, str] = {
    # default tier (own namespace, hard-bounded)
    "basil": "fawlty.guests.basil",      # random crash / CrashLoopBackOff
    "sybil": "fawlty.guests.sybil",      # memory leak -> OOMKilled
    "manuel": "fawlty.guests.manuel",    # flapping readiness
    "kitchen": "fawlty.guests.kitchen",  # CPU hog / throttling
    "waiter": "fawlty.guests.waiter",    # slow HTTP / latency
    "major": "fawlty.guests.major",      # safe outbound egress noise
    "polly": "fawlty.guests.polly",      # log storm
    "oreilly": "fawlty.guests.oreilly",  # Event + Job flood
    "chef": "fawlty.guests.chef",        # ArgoCD drift
    "victim": "fawlty.guests.victim",    # innocent HTTP target
    # node tier (gated; can pressure the node itself)
    "diskfill": "fawlty.guests.diskfill",
    "pidbomb": "fawlty.guests.pidbomb",
    "squatter": "fawlty.guests.squatter",
}


def main() -> int:
    name = common.guest_name()
    log = common.get_logger()
    common.install_signal_handlers()

    module_path = GUESTS.get(name)
    if module_path is None:
        log.error(
            f"unknown guest {name!r}; set FAWLTY_GUEST to one of: "
            + ", ".join(sorted(GUESTS))
        )
        return 2

    log.info(f"checking in guest {name!r} ({module_path})")
    try:
        module = importlib.import_module(module_path)
        module.run()
    except Exception as exc:  # noqa: BLE001 - a guest crashing IS a valid outcome
        log.exception(f"guest {name!r} raised: {exc}")
        return 1
    log.info(f"guest {name!r} finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
