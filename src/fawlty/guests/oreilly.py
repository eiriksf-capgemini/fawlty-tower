"""O'Reilly the builder: makes a mess with Kubernetes objects.

Uses its (namespace-scoped) ServiceAccount to spam Kubernetes Events and spawn
a flood of short-lived Jobs. This clutters `kubectl get events` and the Jobs
list, and churns the API server — the kind of noise a careless CI integration
or a stuck controller produces.

Strictly in-namespace: bind it an RBAC Role that permits only Events and Jobs
in the fawlty-tower namespace. If the token isn't present (running outside the
cluster) it degrades to log-only.

The Jobs are built to pass Pod Security Admission at the `restricted` level
(non-root, no privilege escalation, all capabilities dropped, RuntimeDefault
seccomp, no service-account token), so a hardened namespace sees the intended
Job flood rather than a stream of admission rejections. Their image comes from
FAWLTY_JOB_IMAGE (default busybox:1.36): point it at your registry mirror on
air-gapped clusters or to avoid Docker Hub rate limits.

Events reference the real pod (POD_NAME / POD_UID from the downward API, falling
back to the hostname, which Kubernetes sets to the pod name), so `kubectl
describe pod` shows them and an agent can trace the spam back to its source.
"""
from __future__ import annotations

import datetime as dt
import os
import random
import socket
import uuid

from fawlty import blind, common

EVENT_INTERVAL_S = 3.0
JOB_INTERVAL_S = 15.0
JOB_IMAGE = os.environ.get("FAWLTY_JOB_IMAGE", "busybox:1.36")
JOB_UID = 65534  # "nobody": busybox needs nothing more for echo + sleep

REASONS = ["BuildingSomething", "KnockedItDown", "WrongWall", "SatisfiedCustomer", "Oops"]
# Blind mode: plausible controller-ish reasons that do not name the fault.
NEUTRAL_REASONS = ["SyncStarted", "ConfigReloaded", "CacheRefreshed", "LeaseRenewed", "TaskScheduled"]


def _me() -> str:
    """Name used for created objects: the persona, or FAWLTY_ALIAS when blind."""
    return blind.alias() if blind.enabled() else "oreilly"


def run() -> None:
    log = common.get_logger()
    stop = common.stop_event()
    ns = common.namespace()

    try:
        from kubernetes import client, config  # type: ignore

        config.load_incluster_config()
        core = client.CoreV1Api()
        batch = client.BatchV1Api()
    except Exception as exc:  # noqa: BLE001
        log.warning(f"no in-cluster API access ({exc}); O'Reilly will only log, not spam the API")
        core = batch = None

    log.info(f"O'Reilly reporting for duty in namespace {ns!r}")
    last_job = 0.0
    tick = 0.0

    while not stop.is_set():
        reason = random.choice(NEUTRAL_REASONS if blind.enabled() else REASONS)
        if core is not None:
            _emit_event(core, ns, reason, log)
        else:
            log.warning(f"would emit Event reason={reason} (no API access)")

        if batch is not None and tick - last_job >= JOB_INTERVAL_S:
            _spawn_job(batch, ns, log)
            last_job = tick

        stop.wait(EVENT_INTERVAL_S)
        tick += EVENT_INTERVAL_S


def _emit_event(core, ns: str, reason: str, log) -> None:
    from kubernetes import client  # type: ignore

    now = dt.datetime.now(dt.timezone.utc)
    name = f"{_me()}-{uuid.uuid4().hex[:8]}"
    body = client.CoreV1Event(
        metadata=client.V1ObjectMeta(name=name, namespace=ns),
        involved_object=client.V1ObjectReference(
            kind="Pod", namespace=ns, name=os.environ.get("POD_NAME") or socket.gethostname(),
            uid=os.environ.get("POD_UID") or None,
        ),
        reason=reason,
        message=blind.text(f"O'Reilly did a thing: {reason}", f"{reason} completed"),
        type="Warning",
        event_time=now,
        reporting_component=blind.text("fawlty-tower/oreilly", f"{_me()}-controller"),
        reporting_instance=_me(),
        action=blind.text("Chaos", "Sync"),
        first_timestamp=now,
        last_timestamp=now,
        count=1,
    )
    try:
        core.create_namespaced_event(ns, body)
        log.warning(f"emitted Event {name} reason={reason}")
    except Exception as exc:  # noqa: BLE001
        log.error(f"failed to emit Event: {exc}")


def _spawn_job(batch, ns: str, log) -> None:
    from kubernetes import client  # type: ignore

    name = f"{_me()}-job-{uuid.uuid4().hex[:8]}"
    job = client.V1Job(
        metadata=client.V1ObjectMeta(name=name, namespace=ns, labels={"app": _me()}),
        spec=client.V1JobSpec(
            backoff_limit=0,
            ttl_seconds_after_finished=30,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": _me()}),
                spec=client.V1PodSpec(
                    restart_policy="Never",
                    automount_service_account_token=False,
                    security_context=client.V1PodSecurityContext(
                        run_as_non_root=True,
                        run_as_user=JOB_UID,
                        run_as_group=JOB_UID,
                        seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
                    ),
                    containers=[
                        client.V1Container(
                            name="work",
                            image=JOB_IMAGE,
                            command=["sh", "-c", "echo building...; sleep 2; echo done"],
                            security_context=client.V1SecurityContext(
                                allow_privilege_escalation=False,
                                read_only_root_filesystem=True,
                                capabilities=client.V1Capabilities(drop=["ALL"]),
                            ),
                            resources=client.V1ResourceRequirements(
                                requests={"cpu": "5m", "memory": "8Mi"},
                                limits={"cpu": "50m", "memory": "32Mi"},
                            ),
                        )
                    ],
                ),
            ),
        ),
    )
    try:
        batch.create_namespaced_job(ns, job)
        log.warning(f"spawned Job {name}")
    except Exception as exc:  # noqa: BLE001
        log.error(f"failed to spawn Job: {exc}")
