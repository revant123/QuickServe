#!/usr/bin/env bash
# Run infra/k8s/smoke_test.py inside the cluster, in a short-lived pod of its
# own, labelled app.kubernetes.io/name=smoke-test. The network policies give
# that label exactly what the tests need (see network-policies/tests.yaml).
#
#   infra/k8s/smoke.sh check          # log in, browse, place an order
#   infra/k8s/smoke.sh monitoring     # Prometheus, Grafana, alert emails
#   infra/k8s/smoke.sh watch 60       # 60 s of requests, print JSON stats
#
# It uses the same image the worker runs, so it needs no extra download.
set -euo pipefail

NS=quickserve
IMAGE=$(kubectl -n "$NS" get deployment/worker -o jsonpath='{.spec.template.spec.containers[0].image}')
NAME="smoke-test-$(date +%s)-$RANDOM"

# --rm: delete the pod when it's done. -i: send the script on stdin.
# --quiet: no "pod deleted" line, so `watch` output stays pure JSON.
exec kubectl -n "$NS" run "$NAME" \
  --image="$IMAGE" --image-pull-policy=IfNotPresent --restart=Never \
  --labels=app.kubernetes.io/name=smoke-test \
  --rm -i --quiet \
  --command -- python - "$@" <"$(dirname "$0")/smoke_test.py"
