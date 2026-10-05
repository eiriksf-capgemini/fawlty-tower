"""In-cluster TTL reaper: check out guests whose `fawlty check-in --for` expired.

    python -m fawlty.reaper            # one pass, then exit (run it as a CronJob)

`fawlty check-in --for 10m` only stamps a `fawlty.io/expires-at` annotation;
nothing scales the guest back down unless someone runs `fawlty reap`. A
forgotten check-in therefore ran forever. This module is the same reap logic
as the CLI, runnable from the image itself, so a CronJob can enforce TTLs
without a laptop in the loop. See examples/kustomize/reaper.

Only Deployments labelled app.kubernetes.io/part-of=fawlty-tower are touched.
"""
from __future__ import annotations

import datetime as dt
import time

from fawlty import common

SELECTOR = "app.kubernetes.io/part-of=fawlty-tower"
EXPIRES = "fawlty.io/expires-at"


def expired(deployments, now: float) -> list[str]:
    """Names of Deployments that are scaled up and past their expires-at."""
    out = []
    for d in deployments:
        ann = (d.metadata.annotations or {}) if d.metadata else {}
        exp = ann.get(EXPIRES, "")
        if not exp.isdigit() or int(exp) > now:
            continue
        if (d.spec.replicas or 0) > 0:
            out.append(d.metadata.name)
    return out


def checkout_patch(now: float) -> dict:
    stamp = dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "spec": {"replicas": 0},
        "metadata": {"annotations": {EXPIRES: None, "fawlty.io/checked-out-at": stamp}},
    }


def reap(apps, ns: str, log, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    items = apps.list_namespaced_deployment(ns, label_selector=SELECTOR).items
    names = expired(items, now)
    for name in names:
        apps.patch_namespaced_deployment(name, ns, checkout_patch(now))
        log.warning(f"reaped {name}: TTL expired, scaled to 0")
    if not names:
        log.info("nothing to reap")
    return names


def main() -> int:
    log = common.get_logger()
    from kubernetes import client, config  # type: ignore

    config.load_incluster_config()
    reap(client.AppsV1Api(), common.namespace(), log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
