# Fawlty Tower

A hotel full of badly-behaved guests, for testing agentic ops.

`fawlty-tower` is a set of deliberately faulty workloads for a Kubernetes
cluster. Each "guest" misbehaves in one specific, recognisable way — crashing,
leaking memory, flapping readiness, spamming logs, making noise on the network,
fighting GitOps — so your ops agents and alerting have real failures to detect
and diagnose.

One small image ([`Dockerfile`](Dockerfile)) runs every guest; the
`FAWLTY_GUEST` environment variable picks which one (see
[`src/fawlty/dispatch.py`](src/fawlty/dispatch.py)). This repo holds the source,
the image, and the `fawlty` control CLI. The Kubernetes manifests (one
Deployment per guest, plus the RBAC the API-touching guests need) live in your
own GitOps or config repo; this repo is deliberately infrastructure-agnostic.

## Nothing runs until you say so

Every guest's Deployment ships at `replicas: 0`. Installing fawlty-tower leaves
the cluster perfectly healthy. You check a guest in with the `fawlty` CLI, which
scales it up. If you run Argo CD (or similar), tell it to ignore
`.spec.replicas` for this app so the toggle stays live and is not reverted by
selfHeal.

```sh
fawlty roster                  # who's in, who's out
fawlty check-in basil sybil    # start one or more guests
fawlty check-out basil         # stop them
fawlty check-in --tier node    # start a whole tier (default | node | all)
fawlty evict-all               # quiet hotel: every guest back to 0
fawlty panic                   # evict-all, then bounce your real workloads
```

`fawlty panic` bounces only the namespaces you name in `FAWLTY_REAL_NS`
(space-separated, e.g. `export FAWLTY_REAL_NS="argocd my-app"`); unset, it just
evicts every guest. The CLI needs no knowledge of your cluster beyond a
`kubectl` context.

## The guests

### Default tier (own namespace, hard-bounded)

Each pod has small CPU/memory limits, so its fault stays inside its own cgroup
and never threatens the node.

| Guest | Misbehaviour | Signal an ops agent should catch |
|---|---|---|
| **Basil** | storms out at random | CrashLoopBackOff, climbing restart count |
| **Sybil** | hoards memory forever | steady RSS climb then OOMKilled, restart loop |
| **Manuel** | "I know nothing" | readiness flaps Ready/NotReady, endpoint churn |
| **The Kitchen** | always slammed | CPU pinned at its limit, CFS throttling |
| **The Waiter** | terribly slow service | high latency, probe timeouts |
| **The Major** | wanders off | constant (safe, allowlisted) outbound requests |
| **Polly** | screeches | high-volume benign ERROR/WARN log storm |
| **O'Reilly** | makes a mess | Kubernetes Event spam + short-lived Job flood |
| **The Chef** | never does as told | patches his own Deployment, fighting Argo CD selfHeal |
| **the victim** | perfectly innocent | a stable HTTP target to break |

The Major only ever issues GETs against a fixed allowlist of harmless public
sites (`src/fawlty/common.py`); it is never pointed at an arbitrary host.
O'Reilly and the Chef touch the Kubernetes API through a ServiceAccount whose
RBAC should be scoped to the `fawlty-tower` namespace only.

### Node tier (gated, off by default)

These reach past their own pod to pressure the **node**, and on a single-node
cluster can evict critical workloads such as Argo CD. They are gated twice — not
deployed unless you add them, and still `replicas: 0` after that.

| Guest | Misbehaviour |
|---|---|
| **diskfill** | writes ballast to a node hostPath toward DiskPressure |
| **pidbomb** | thread storm toward the PID table (self-capped) |
| **squatter** | hostNetwork pod squatting node port 80, fighting ingress |

## Building

```sh
docker build -t fawlty-tower:test .
FAWLTY_GUEST=major docker run --rm fawlty-tower:test
```

Push the image to wherever your cluster pulls from, then roll the pods so they
pick up the new build. Every guest runs from this one image and differs only by
its `FAWLTY_GUEST` env var.

## Adding a guest

1. Add `src/fawlty/guests/<name>.py` exposing `run()`.
2. Register it in `GUESTS` in `src/fawlty/dispatch.py`.
3. Add a Deployment (at `replicas: 0`) for it in your manifests.
4. Add the name to the relevant tier list in the `fawlty` CLI.
