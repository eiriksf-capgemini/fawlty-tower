"""O'Reilly the builder: makes a mess with Kubernetes objects.

Uses its (namespace-scoped) ServiceAccount to spam Kubernetes Events and spawn
a flood of short-lived Jobs. This clutters `kubectl get events` and the Jobs
list, and churns the API server — the kind of noise a careless CI integration
or a stuck controller produces.

Strictly in-namespace: bind it an RBAC Role that permits only Events and Jobs
in the fawlty-tower namespace. If the token isn't present (running outside the
cluster) it degrades to log-only.
"""
from __future__ import annotations

import datetime as dt
import random
import uuid

from fawlty import common

EVENT_INTERVAL_S = 3.0
JOB_INTERVAL_S = 15.0

REASONS = ["BuildingSomething", "KnockedItDown", "WrongWall", "SatisfiedCustomer", "Oops"]


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
        reason = random.choice(REASONS)
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
    name = f"oreilly-{uuid.uuid4().hex[:8]}"
    body = client.CoreV1Event(
        metadata=client.V1ObjectMeta(name=name, namespace=ns),
        involved_object=client.V1ObjectReference(kind="Pod", namespace=ns, name="oreilly"),
        reason=reason,
        message=f"O'Reilly did a thing: {reason}",
        type="Warning",
        event_time=now,
        reporting_component="fawlty-tower/oreilly",
        reporting_instance="oreilly",
        action="Chaos",
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

    name = f"oreilly-job-{uuid.uuid4().hex[:8]}"
    job = client.V1Job(
        metadata=client.V1ObjectMeta(name=name, namespace=ns, labels={"app": "oreilly"}),
        spec=client.V1JobSpec(
            backoff_limit=0,
            ttl_seconds_after_finished=30,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": "oreilly"}),
                spec=client.V1PodSpec(
                    restart_policy="Never",
                    containers=[
                        client.V1Container(
                            name="work",
                            image="busybox:1.36",
                            command=["sh", "-c", "echo building...; sleep 2; echo done"],
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
