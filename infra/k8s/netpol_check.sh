#!/usr/bin/env bash
# Prove the network policies (Phase 10) are ENFORCED, not just accepted.
#
#   infra/k8s/netpol_check.sh
#
# Kubernetes stores a NetworkPolicy even when the network plugin ignores it,
# so "kubectl apply" succeeding proves nothing. This script tries real
# connections from real pods: the allowed ones must connect, the forbidden ones
# must fail. The allowed ones matter as much: without them, a broken test that
# fails EVERY connection would look like perfect security.
set -euo pipefail

NS=quickserve
TEST_NS=netpol-test # a namespace with no policies: the "rest of the cluster"
IMAGE=$(kubectl -n "$NS" get deployment/worker -o jsonpath='{.spec.template.spec.containers[0].image}')
cleanup() { kubectl delete namespace "$TEST_NS" --ignore-not-found --wait=false >/dev/null; }
trap cleanup EXIT

# Runs inside a pod: tries each host:port:expected and reports.
PROBE='
import socket, sys
who, bad = sys.argv[1], 0
for spec in sys.argv[2:]:
    host, port, want = spec.split(":")
    try:
        socket.getaddrinfo(host, None)
    except OSError:  # DNS must work everywhere; a failure here is a broken test
        print(f"   ERROR {who} -> {host}:{port}: DNS lookup failed")
        bad += 1
        continue
    s = socket.socket()
    s.settimeout(3)
    got = "open" if s.connect_ex((host, int(port))) == 0 else "blocked"
    s.close()
    mark = "ok  " if got == want else "FAIL"
    print(f"   {mark} {who:<10} -> {host}:{port:<5} {got:<7} (expected {want})")
    bad += got != want
sys.exit(1 if bad else 0)
'

from_deployment() { # deployment, then host:port:expected...
  local d=$1
  shift
  kubectl -n "$NS" exec -i "deploy/$d" -c "$d" -- python - "$d" "$@" <<<"$PROBE"
}

from_new_pod() { # namespace, label, then host:port:expected...
  local ns=$1 label=$2
  shift 2
  kubectl -n "$ns" run "probe-$RANDOM" --image="$IMAGE" --image-pull-policy=IfNotPresent \
    --restart=Never --labels="app.kubernetes.io/name=$label" --rm -i --quiet \
    --command -- python - "$label" "$@" <<<"$PROBE"
}

failed=0
echo "Inside quickserve: each app reaches only what it needs"
from_deployment api postgres:5432:open redis:6379:open prometheus:9090:blocked 1.1.1.1:443:blocked || failed=1
from_deployment worker postgres:5432:open api:80:blocked redis:6379:blocked 1.1.1.1:443:blocked || failed=1
from_deployment notifier postgres:5432:open api:80:blocked || failed=1
from_new_pod "$NS" smoke-test api:80:open postgres:5432:blocked redis:6379:blocked || failed=1

echo "From another namespace (a pod with NO policies of its own)"
kubectl create namespace "$TEST_NS" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
from_new_pod "$TEST_NS" intruder \
  "postgres.$NS:5432:blocked" "redis.$NS:6379:blocked" "api.$NS:80:blocked" "prometheus.$NS:9090:blocked" \
  quickserve-gateway.envoy-gateway-system:443:open 1.1.1.1:443:open || failed=1
# The last two are the controls: the front door is open to everyone, and this
# pod really can make connections, so "blocked" above means the policy did it.

if ((failed)); then
  echo "Network policies are NOT working as written."
  exit 1
fi
echo
echo "Network policies enforced."
