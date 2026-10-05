"""The Chef: never does what he's told. Fights GitOps.

Periodically patches its own Deployment — flipping the value of a label that
your manifests DECLARE — so Argo CD's selfHeal has to keep reverting it. The
result is a Deployment that flaps between Synced and OutOfSync forever, plus a
stream of Argo CD sync activity. This is the drift signal an ops agent should
flag as "something keeps changing this out-of-band."

The label must be declared in Git (e.g. `chef-mood: calm` on the Deployment's
metadata.labels). Argo CD's diff only compares fields present in the desired
state: a label or annotation that exists only in the live object is not drift,
so the Chef's original "add a nonsense annotation" behaviour could run forever
without ever producing OutOfSync. The Chef checks for the declared label on
start-up and warns loudly if it is missing.

Deliberately NOT exempted from selfHeal: the fight is the whole point. (Exempt
only the replicas field from selfHeal so the fawlty CLI's scale toggle survives.)

RBAC: get + patch on deployments, ideally restricted with
`resourceNames: [<this deployment>]` so the Chef can only fight with himself.
"""
from __future__ import annotations

import os

from fawlty import common

DEPLOYMENT = os.environ.get("FAWLTY_SELF_DEPLOYMENT", "chef")
LABEL = os.environ.get("FAWLTY_CHEF_LABEL", "chef-mood")
MOODS = ("sulking", "furious")  # n=1 -> furious, as before
INTERVAL_S = float(os.environ.get("FAWLTY_CHEF_INTERVAL_S", "20.0"))


def _check_label_declared(apps, ns: str, log) -> None:
    """Warn if the drift label is absent: without it there is nothing to revert."""
    try:
        live = apps.read_namespaced_deployment(DEPLOYMENT, ns)
    except Exception as exc:  # noqa: BLE001
        log.warning(f"could not read Deployment {ns}/{DEPLOYMENT} to check label {LABEL!r}: {exc}")
        return
    labels = (live.metadata.labels or {}) if live.metadata else {}
    if LABEL not in labels:
        log.warning(
            f"label {LABEL!r} is not set on Deployment {DEPLOYMENT}; declare it in Git "
            f"(e.g. {LABEL}: calm) or Argo CD will not treat the Chef's changes as drift"
        )


def _patch_body(n: int) -> dict:
    mood = MOODS[n % len(MOODS)]
    return {
        "metadata": {
            "annotations": {"fawlty.chef/rearranged-at": str(n)},
            "labels": {LABEL: mood},
        }
    }


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
    if apps is not None:
        _check_label_declared(apps, ns, log)

    n = 0
    while not stop.is_set():
        if apps is not None:
            n += 1
            patch = _patch_body(n)
            mood = patch["metadata"]["labels"][LABEL]
            try:
                apps.patch_namespaced_deployment(DEPLOYMENT, ns, patch)
                log.warning(f"rearranged Deployment {DEPLOYMENT} ({LABEL}={mood}, drift #{n}) — Argo CD will undo it")
            except Exception as exc:  # noqa: BLE001
                log.error(f"failed to patch Deployment {DEPLOYMENT}: {exc}")
        stop.wait(INTERVAL_S)
