"""Sybil: hoards everything. A steady memory leak.

Allocates memory in fixed chunks and never lets go, logging the climb, until the
container's memory limit trips an OOMKill and Kubernetes restarts it — then it
starts hoarding again. Produces the sawtooth RSS graph and OOMKilled restart
loop that memory leaks are famous for. Bounded by the Deployment's memory limit,
so only Sybil's own pod dies, never the node.
"""
from __future__ import annotations

import os

from fawlty import common

CHUNK_MB = 16
INTERVAL_S = float(os.environ.get("FAWLTY_LEAK_INTERVAL_S", "2.0"))


def run() -> None:
    log = common.get_logger()
    stop = common.stop_event()
    hoard: list[bytearray] = []
    held_mb = 0

    log.info("Sybil starts collecting things she absolutely must keep")
    while not stop.is_set():
        # Touch every page so the pages are actually resident, not just reserved.
        block = bytearray(CHUNK_MB * 1024 * 1024)
        for i in range(0, len(block), 4096):
            block[i] = 1
        hoard.append(block)
        held_mb += CHUNK_MB
        log.warning(f"Sybil is now hoarding {held_mb}MiB and shows no sign of stopping")
        stop.wait(INTERVAL_S)
