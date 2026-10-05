#!/usr/bin/env bash
# Behavioural tests for ./fawlty using a stub kubectl (no cluster needed).
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
export KUBECTL_LOG="$TMP/kubectl.log" STUB_CTX="${STUB_CTX:-kind-test}" CTX_FILE="$TMP/ctx"
mkdir "$TMP/bin"
cat > "$TMP/bin/kubectl" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$KUBECTL_LOG"
case "$*" in
  "config current-context") if [ -s "$CTX_FILE" ]; then cat "$CTX_FILE"; else echo "$STUB_CTX"; fi ;;
  *" scale deploy "*)
    # Simulate someone switching context right after the first scale call.
    if [ -n "${FLIP_CTX_ON_SCALE:-}" ] && [ ! -s "$CTX_FILE" ]; then echo "$FLIP_CTX_ON_SCALE" > "$CTX_FILE"; fi
    if [ -n "${FAIL_SCALE:-}" ]; then echo "Error from server (Forbidden)" >&2; exit 1; fi ;;
  *"get deploy -o custom-columns"*) printf 'basil 1 1 <none>\nsybil 0 <none> 1\n' ;;
  *"rollout restart"*--all*) echo "error: unknown flag: --all" >&2; exit 1 ;;
  *"get deploy "*|*"get ns "*) exit 0 ;;
esac
exit 0
STUB
chmod +x "$TMP/bin/kubectl"
export PATH="$TMP/bin:$PATH"
unset FAWLTY_ALLOWED_CONTEXTS FAWLTY_ALLOW_ANY_CONTEXT FAWLTY_ASSUME_YES FAWLTY_REAL_NS FAWLTY_LOG

fails=0
check() { # name expected_rc actual_rc
  if [ "$2" = "$3" ]; then echo "ok   - $1"; else echo "FAIL - $1 (rc want $2 got $3)"; fails=$((fails+1)); fi
}
scales() { grep -c ' scale deploy ' "$KUBECTL_LOG" || true; }
reset() { : > "$KUBECTL_LOG"; }

reset; FAWLTY_ALLOWED_CONTEXTS=kind-test "$ROOT/fawlty" evict-all >/dev/null 2>&1; rc=$?
check "evict-all succeeds on allowed context" 0 "$rc"
check "evict-all scales all 13 guests" 13 "$(scales)"

reset; FAWLTY_ALLOWED_CONTEXTS=prod "$ROOT/fawlty" evict-all >/dev/null 2>&1; rc=$?
check "wrong context is refused" 1 "$rc"
check "wrong context makes no scale calls" 0 "$(scales)"

reset; "$ROOT/fawlty" check-in basil >/dev/null 2>&1; rc=$?
check "default-tier check-in without allowlist is refused" 1 "$rc"
check "  ...and makes no scale calls" 0 "$(scales)"

reset; FAWLTY_ALLOW_ANY_CONTEXT=1 "$ROOT/fawlty" check-in basil >/dev/null 2>&1; rc=$?
check "FAWLTY_ALLOW_ANY_CONTEXT=1 opts out for the default tier" 0 "$rc"

reset; FAWLTY_ALLOW_ANY_CONTEXT=1 "$ROOT/fawlty" check-in diskfill --yes >/dev/null 2>&1; rc=$?
check "FAWLTY_ALLOW_ANY_CONTEXT never relaxes the node tier" 1 "$rc"

reset; FAWLTY_ALLOWED_CONTEXTS=kind-test "$ROOT/fawlty" check-in basil >/dev/null 2>&1
unpinned=$(grep -v '^config current-context$' "$KUBECTL_LOG" | grep -vc '^--context kind-test ' || true)
check "every cluster call is pinned with --context" 0 "$unpinned"

# Switch context mid --wait: the EXIT-trap check-out must still hit kind-test.
reset; rm -f "$CTX_FILE"
FLIP_CTX_ON_SCALE=prod FAWLTY_ALLOWED_CONTEXTS=kind-test "$ROOT/fawlty" check-in basil --for 1s --wait >/dev/null 2>&1; rc=$?
flipped=$(cat "$CTX_FILE" 2>/dev/null); rm -f "$CTX_FILE"
check "check-in --wait succeeds" 0 "$rc"
check "  ...the context really was switched mid-run" prod "$flipped"
grep -q -- '--context kind-test -n fawlty-tower scale deploy basil --replicas=0' "$KUBECTL_LOG"
check "  ...check-out after a context switch still targets the approved context" 0 $?
grep -q -- '--context prod' "$KUBECTL_LOG"; check "  ...and never touches the new context" 1 $?

reset; FAWLTY_ALLOWED_CONTEXTS=kind-test "$ROOT/fawlty" check-in basil --for 1h --wait >/dev/null 2>&1 &
pid=$!; for _ in $(seq 1 50); do grep -q 'replicas=1' "$KUBECTL_LOG" && break; sleep 0.1; done
start=$SECONDS; kill -TERM "$pid"; wait "$pid"; rc=$?
check "SIGTERM during --wait exits promptly" 1 "$(( SECONDS - start < 5 ))"
grep -q 'scale deploy basil --replicas=0' "$KUBECTL_LOG"; check "  ...and checks the guest out" 0 $?

reset; FAIL_SCALE=1 FAWLTY_ALLOWED_CONTEXTS=kind-test "$ROOT/fawlty" check-in basil >/dev/null 2>&1; rc=$?
check "a failed kubectl scale is reported as failure" 1 "$rc"
reset; FAIL_SCALE=1 FAWLTY_ALLOWED_CONTEXTS=kind-test "$ROOT/fawlty" evict-all >/dev/null 2>&1; rc=$?
check "  ...including by evict-all" 1 "$rc"

reset; FAWLTY_ALLOWED_CONTEXTS=kind-test "$ROOT/fawlty" check-in basil --for 09s >/dev/null 2>&1; rc=$?
check "durations with a leading zero are decimal" 0 "$rc"
grep -q "expires-at=" "$KUBECTL_LOG"; check "  ...and still set the TTL" 0 $?

reset; FAWLTY_ALLOWED_CONTEXTS=kind-test "$ROOT/fawlty" check-in basil --tier bogus >/dev/null 2>&1; rc=$?
check "unknown tier is fatal" 1 "$rc"
check "  ...and makes no scale calls" 0 "$(scales)"

reset; FAWLTY_ALLOWED_CONTEXTS=kind-test "$ROOT/fawlty" check-out diskfill >/dev/null 2>&1; rc=$?
check "check-out of a deployed guest succeeds" 0 "$rc"

reset; FAWLTY_ALLOWED_CONTEXTS=kind-test "$ROOT/fawlty" check-in diskfill >/dev/null 2>&1; rc=$?
check "node guest without --yes is refused" 1 "$rc"
check "node guest without --yes makes no scale calls" 0 "$(scales)"

reset; "$ROOT/fawlty" check-in diskfill --yes >/dev/null 2>&1; rc=$?
check "node guest without allowlist is refused" 1 "$rc"

reset; FAWLTY_ALLOWED_CONTEXTS=kind-test "$ROOT/fawlty" check-in diskfill --yes >/dev/null 2>&1; rc=$?
check "node guest with --yes + allowlist works" 0 "$rc"
grep -q 'replicas=1' "$KUBECTL_LOG"; check "  ...and scaled to 1" 0 $?

reset; FAWLTY_ALLOWED_CONTEXTS=kind-test "$ROOT/fawlty" check-in --tier all >/dev/null 2>&1; rc=$?
check "--tier all without --yes is refused" 1 "$rc"

reset; FAWLTY_ALLOWED_CONTEXTS=kind-test "$ROOT/fawlty" check-in basil --for 10m >/dev/null 2>&1; rc=$?
check "check-in with TTL works" 0 "$rc"
grep -q 'fawlty.io/expires-at=' "$KUBECTL_LOG"; check "  ...and sets expires-at annotation" 0 $?

reset; "$ROOT/fawlty" check-in basil --for banana >/dev/null 2>&1; rc=$?
check "bad duration rejected" 1 "$rc"

reset; "$ROOT/fawlty" check-in nobody >/dev/null 2>&1; rc=$?
check "unknown guest rejected" 1 "$rc"

reset; "$ROOT/fawlty" check-in basil --bogus >/dev/null 2>&1; rc=$?
check "unknown flag rejected" 1 "$rc"

reset; "$ROOT/fawlty" check-out basil --for 5m >/dev/null 2>&1; rc=$?
check "--for on check-out rejected" 1 "$rc"

reset; FAWLTY_LOG="$TMP/events.log" FAWLTY_ALLOWED_CONTEXTS=kind-test "$ROOT/fawlty" check-in basil >/dev/null 2>&1
grep -q 'check-in basil' "$TMP/events.log"; check "FAWLTY_LOG records events" 0 $?

reset; out=$("$ROOT/fawlty" roster 2>&1)
grep -Eq 'basil +default +1 +1' <<<"$out"; check "roster renders deployed guest" 0 $?
grep -Eq 'sybil +default +0 +0 +expired' <<<"$out"; check "roster shows expired TTL and defaults <none> to 0" 0 $?
grep -q 'diskfill.*not deployed' <<<"$out"; check "roster flags undeployed guests" 0 $?
reset; "$ROOT/fawlty" roster >/dev/null 2>&1
check "roster uses a single deployment query" 1 "$(grep -c 'get deploy' "$KUBECTL_LOG")"

reset; FAWLTY_ALLOWED_CONTEXTS=kind-test FAWLTY_REAL_NS="app" "$ROOT/fawlty" panic >/dev/null 2>&1; rc=$?
check "panic succeeds" 0 "$rc"
for k in deployment statefulset daemonset; do
  grep -q "rollout restart $k" "$KUBECTL_LOG"; check "  ...restarts ${k}s" 0 $?
done

"$ROOT/fawlty" help >/dev/null 2>&1; check "help works without kubectl context" 0 $?
echo "diagnosis: pod is healthy, nothing wrong" | "$ROOT/fawlty" grade victim - >/dev/null 2>&1
check "grade victim negative control passes" 0 $?
echo "victim is unhealthy and failing" | "$ROOT/fawlty" grade victim - >/dev/null 2>&1
check "grade victim negative control fails on an invented problem" 1 $?

if [ "$fails" -eq 0 ]; then echo "all CLI tests passed"; else echo "$fails CLI test(s) failed"; exit 1; fi
