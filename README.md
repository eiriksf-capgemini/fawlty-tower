# Fawlty Tower

A hotel full of badly-behaved guests, for testing agentic ops.

Fawlty Tower is a **chaos harness**: a small collection of workloads that break
*on purpose*, in specific and recognisable ways, so you can see whether your
cluster's observability and ops tooling actually notices and correctly diagnoses
each failure — before a real incident finds out for you.

## What is a chaos harness?

Chaos engineering is the practice of deliberately injecting faults into a running
system to learn how it behaves under stress, instead of waiting for an outage to
teach you the hard way. A *chaos harness* is the tooling that produces those
faults on demand.

Most chaos tools test whether the **application** survives — can it tolerate a
killed pod, a slow dependency, a lost node? Fawlty Tower points the same idea at
a different target: the **ops layer** that is supposed to be watching. Its guests
don't exist to see if your app recovers; they exist to generate real, labelled
failures so you can answer questions like:

- Does my alerting fire on a CrashLoopBackOff, and how fast?
- Can my dashboards tell a genuine error storm from harmless log noise?
- When an ops agent (a runbook automation, a `cluster-doctor` CronJob, an
  LLM-driven diagnoser) looks at the cluster, does it reach the *right*
  conclusion about what's wrong?

Because every fault here is known in advance, you have ground truth: you know
exactly what broke, so you can grade whether your tooling got it right.

## How it works

Each **guest** is one fault persona — one container that misbehaves in exactly
one way. They all run from a single image
([`Dockerfile`](Dockerfile)); the `FAWLTY_GUEST` environment variable selects
which persona a given pod runs (see [`src/fawlty/dispatch.py`](src/fawlty/dispatch.py)).

Three things keep this safe to run against a real cluster:

1. **Nothing runs until you say so.** Every guest's Deployment ships at
   `replicas: 0`. Installing Fawlty Tower leaves the cluster perfectly healthy;
   you check guests in one at a time.
2. **Faults are bounded.** Default-tier guests carry small CPU and memory limits,
   so a fault stays inside its own cgroup and never threatens the node. The
   network guest only ever calls a fixed allowlist of public sites; the
   API-touching guests use a namespace-scoped ServiceAccount.
3. **The dangerous ones are gated.** A separate *node tier* can pressure the node
   itself (disk, PIDs, host ports) and is off by default and documented as such.

This repo holds the source, the image, and the `fawlty` control CLI. The
Kubernetes manifests (one Deployment per guest, plus the RBAC the API-touching
guests need) live in your own GitOps or config repo — Fawlty Tower is
deliberately infrastructure-agnostic and ships no cluster-specific config.

## Using it

### Prerequisites

- A Kubernetes cluster you are comfortable breaking (a local `kind`, `minikube`,
  or colima cluster is ideal).
- `kubectl` pointed at that cluster.
- A container registry the cluster can pull from.
- Deployment manifests for the guests in your own config repo (see
  [Deploying](#deploying)).

### Build the image

```sh
docker build -t fawlty-tower:test .

# Run any single guest locally to see it misbehave:
FAWLTY_GUEST=major docker run --rm fawlty-tower:test
```

Push the image to wherever your cluster pulls from. Every guest runs from this
one image and differs only by its `FAWLTY_GUEST` env var.

### Deploying

Add one Deployment per guest to your config repo, each at `replicas: 0`, each
setting `FAWLTY_GUEST` to the guest's name. Give O'Reilly and the Chef a
ServiceAccount whose RBAC is scoped to the `fawlty-tower` namespace only. If you
run Argo CD (or similar), tell it to **ignore `.spec.replicas`** for this app, so
the `fawlty` CLI's live scale toggle is not reverted by selfHeal.

For the Chef's drift to be visible, his Deployment must **declare** the label he
flips (default `chef-mood: calm`, override with `FAWLTY_CHEF_LABEL`). Argo CD only
diffs fields that exist in Git, so a label that is only ever set live is not
drift. Restrict his Role to `get`/`patch` on `deployments` with
`resourceNames: [chef]`.

### Checking guests in and out

The `fawlty` CLI is the control surface. It scales a guest's Deployment to 1 to
check it in and back to 0 to check it out:

```sh
fawlty roster                  # who's in, who's out
fawlty check-in basil sybil    # start one or more guests
fawlty check-out basil         # stop them
fawlty check-in --tier node    # start a whole tier (default | node | all)
fawlty evict-all               # quiet hotel: every guest back to 0
fawlty panic                   # evict-all, then bounce your real workloads
```

The CLI needs nothing but a working `kubectl` context.

### Recovering

`fawlty evict-all` returns every guest to `replicas: 0`. If a node-tier guest
disrupted a real workload, `fawlty panic` does an `evict-all` and then restarts
the deployments in the namespaces you name in `FAWLTY_REAL_NS`:

```sh
export FAWLTY_REAL_NS="argocd my-app another-app"
fawlty panic
```

Unset, `panic` just evicts the guests; it never touches anything you haven't
explicitly listed.

## Safety rails

```
export FAWLTY_ALLOWED_CONTEXTS="kind-fawlty minikube"   # clusters fawlty may touch (required)
fawlty check-in basil --for 10m     # marks an expiry; only enforced when `fawlty reap` runs (cron / loop)
fawlty check-in basil --for 10m --wait   # block, then check out (Ctrl-C checks out early)
fawlty check-in --tier node --yes   # node tier needs --yes AND the allowlist
export FAWLTY_LOG=/tmp/fawlty.log   # "<ts> check-in basil" lines, for time-to-detect
```

Each check-in/out also stamps `fawlty.io/checked-in-at`, `fawlty.io/checked-out-at`
and `fawlty.io/expires-at` annotations on the Deployment.

Every command that changes the cluster refuses to run unless the current
kubectl context is in `FAWLTY_ALLOWED_CONTEXTS`. For a throwaway local cluster
you can opt out with `FAWLTY_ALLOW_ANY_CONTEXT=1` (default tier only; the node
tier always needs the allowlist). The context is resolved once at start-up and
passed as `--context` to every kubectl call, so switching contexts in another
terminal during `--wait` cannot redirect the final check-out to another cluster.

## Grading your ops tooling

`scenarios/scenarios.json` is the ground truth: for every guest, the fault, the
expected root cause, concept groups a correct diagnosis must cover, and common
misdiagnoses. `victim` is a negative control: the right answer is "nothing is wrong",
and any misdiagnosis fails it outright (no `--strict` needed).

Phrases match on a word boundary (`healthy` does not match `unhealthy`), and a
mention negated in the same clause (`not OOMKilled`) is ignored rather than
counted, so an agent that explicitly rules something out is not penalised for it.

```
fawlty explain sybil
echo "Container OOMKilled after memory climbed to its limit; restart loop" | fawlty grade sybil -
fawlty grade basil diagnosis.txt --strict --json
```

The keyword grader is a deterministic first gate for CI. For reasoning quality, pass
`fawlty explain <guest>` plus the agent's output to an LLM judge.

## Tests

```
python3 -m unittest discover -s tests   # scenario schema + grader
tests/test_cli.sh                       # CLI behaviour against a stub kubectl
```

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
| **The Chef** | never does as told | flips a Git-declared label on his Deployment, fighting Argo CD selfHeal (OutOfSync flapping) |
| **the victim** | perfectly innocent | a stable HTTP target to break |

Basil exits with ordinary application codes (1, 2, 17, 42). 137 and 139 are
left out on purpose because they look like an OOMKill and a segfault; set
`FAWLTY_EXIT_CODES` (e.g. `1,137`) if you want that ambiguity.

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

## Tuning a guest

Most guests read a few environment variables so you can dial the fault up or
down without rebuilding — for example `FAWLTY_FILL_MB` (diskfill's disk budget),
`FAWLTY_PID_MAX` (pidbomb's thread cap), `FAWLTY_HEALTHY_S` / `FAWLTY_UNHEALTHY_S`
(Manuel's flap cycle), and `FAWLTY_CPU_WORKERS` (the Kitchen's busy threads). See
each guest's module under `src/fawlty/guests/` for its knobs and defaults.

## Adding a guest

1. Add `src/fawlty/guests/<name>.py` exposing `run()`.
2. Register it in `GUESTS` in `src/fawlty/dispatch.py`.
3. Add a Deployment (at `replicas: 0`) for it in your manifests.
4. Add the name to the relevant tier list in the `fawlty` CLI.

## License

MIT — see [LICENSE](LICENSE).
