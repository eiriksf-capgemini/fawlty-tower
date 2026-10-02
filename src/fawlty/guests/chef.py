"""The Chef: never does what he's told. Fights GitOps.

Periodically patches its own Deployment — bumping a nonsense annotation and
flipping a label — so Argo CD's selfHeal has to keep reverting it. The result
is a Deployment that flaps between Synced and OutOfSync forever, plus a stream
of Argo CD sync activity. This is the drift signal an ops agent should flag as
"something keeps changing this out-of-band."

Deliberately NOT exempted from selfHeal: the fight is the whole point. (Exempt
only the replicas field from selfHeal so the fawlty CLI's scale toggle survives.)
"""
from __future__ import annotations

import os

from fawlty import common

DEPLOYMENT = os.environ.get("FAWLTY_SELF_DEPLOYMENT", "chef")
INTERVAL_S = 20.0


def run() -> None:
    log = common.get_logger()
    stop = common.stop_event()
    ns = common.namespace()

    try:
        from kubernetes import client, config  # type: ignore

        config.load_incluster_config()
        apps = client.AppsV1Api()
    except Exception as exc:  # noqa: BLE001
        log.warning(f"no in-cluster API access ({exc}); the Chef can only sulk, not drift")
        apps = None

    log.info(f"the Chef is in the kitchen, will rearrange Deployment {ns}/{DEPLOYMENT}")
    n = 0
    while not stop.is_set():
        if apps is not None:
            n += 1
            patch = {
                "metadata": {
                    "annotations": {"fawlty.chef/rearranged-at": str(n)},
                    "labels": {"chef-mood": "furious" if n % 2 else "sulking"},
                }
            }
            try:
                apps.patch_namespaced_deployment(DEPLOYMENT, ns, patch)
                log.warning(f"rearranged Deployment {DEPLOYMENT} (drift #{n}) — Argo CD will undo it")
            except Exception as exc:  # noqa: BLE001
                log.error(f"failed to patch Deployment {DEPLOYMENT}: {exc}")
        stop.wait(INTERVAL_S)
