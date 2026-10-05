"""diskfill (NODE TIER, GATED): fills a mounted volume toward DiskPressure.

Writes an ever-growing file into FAWLTY_FILL_DIR until it hits FAWLTY_FILL_MB or
the filesystem refuses. When pointed at a hostPath on a single-node kind
cluster, this pushes the node toward DiskPressure, which the kubelet answers by
evicting pods — including, potentially, critical workloads. That is why this is
gated off by default and documented as "may strand the stack".

The ballast is fresh random bytes for every chunk, not zeros and not one
random chunk repeated: on filesystems with transparent compression or
deduplication (btrfs, ZFS, some CSI drivers) zeros compress to nothing and a
repeated chunk dedups to a single copy, so neither would ever move the node
toward DiskPressure.

Bounded by FAWLTY_FILL_MB so a check-in doesn't run the host disk to zero. The
ballast file is truncated on start (opened "wb", not "ab"), so a crash/restart
cycle refills from zero rather than stacking a fresh FILL_MB onto a leftover
file and breaching the bound.
"""
from __future__ import annotations

import os

from fawlty import common

FILL_DIR = os.environ.get("FAWLTY_FILL_DIR", "/fill")
FILL_MB = int(os.environ.get("FAWLTY_FILL_MB", "2048"))
CHUNK_MB = 16


def run() -> None:
    log = common.get_logger()
    stop = common.stop_event()
    os.makedirs(FILL_DIR, exist_ok=True)
    target = os.path.join(FILL_DIR, "fawlty-ballast.bin")
    written = 0

    log.warning(f"diskfill engaged: writing up to {FILL_MB}MiB into {target}")
    # Truncate ("wb"): if a previous run was OOMKilled/evicted before cleanup,
    # start fresh so total on-disk ballast never exceeds FILL_MB.
    with open(target, "wb", buffering=0) as fh:
        while not stop.is_set() and written < FILL_MB:
            try:
                # New bytes each time: incompressible AND undedupable (module docstring).
                fh.write(os.urandom(CHUNK_MB * 1024 * 1024))
                os.fsync(fh.fileno())
                written += CHUNK_MB
                log.warning(f"ballast now {written}MiB / {FILL_MB}MiB")
            except OSError as exc:
                log.error(f"write failed at {written}MiB (disk likely full): {exc}")
                break
            stop.wait(0.5)

    log.warning(f"diskfill holding {written}MiB until terminated")
    stop.wait()
    # On graceful shutdown, clean up so a scale-down actually frees the space.
    try:
        os.remove(target)
        log.info(f"removed ballast {target}")
    except OSError:
        pass
