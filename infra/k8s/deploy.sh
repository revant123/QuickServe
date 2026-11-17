#!/usr/bin/env bash
# Deploy QuickServe to the current Kubernetes cluster, in the right order.
#
#   infra/k8s/deploy.sh                       # minikube on your Mac
#   infra/k8s/deploy.sh infra/k8s/overlays/ci # what CI uses
#
# Order: database and Redis -> migration Job -> API and worker. The API and
# worker pods also wait for the migration themselves (init containers), so the
# order holds even if someone runs `kubectl apply` by hand.
set -euo pipefail

OVERLAY="${1:-infra/k8s/overlays/local}"
NS=quickserve

# A Job's pod spec can't change after it's created. Delete last deploy's Job so
# this deploy's image runs its migrations.
kubectl -n "$NS" delete job migrate --ignore-not-found --wait=true >/dev/null 2>&1 || true

# Was QuickServe already running before this deploy?
ALREADY_DEPLOYED=$(kubectl -n "$NS" get deployment api -o name 2>/dev/null || true)

kubectl apply -k "$OVERLAY"

echo "Waiting for PostgreSQL and Redis..."
kubectl -n "$NS" rollout status statefulset/postgres --timeout=180s
kubectl -n "$NS" rollout status deployment/redis --timeout=120s

echo "Waiting for the migration Job..."
kubectl -n "$NS" wait --for=condition=complete job/migrate --timeout=300s

# The local overlay runs the moving `main` tag. If nothing in the YAML changed,
# `kubectl apply` leaves the old pods alone, still on yesterday's code. A
# restart makes new pods, and imagePullPolicy: Always makes them fetch the
# newest `main` from ghcr.io. (Immutable sha- tags don't need this: a new tag
# is a change in the YAML, so Kubernetes rolls the pods by itself.)
if [[ -n "$ALREADY_DEPLOYED" && "$OVERLAY" != *ci* ]]; then
  echo "Restarting the API and worker to pick up the newest image..."
  kubectl -n "$NS" rollout restart deployment/api deployment/worker deployment/notifier
fi

echo "Waiting for the API, the worker and the notifier..."
kubectl -n "$NS" rollout status deployment/api --timeout=300s
kubectl -n "$NS" rollout status deployment/worker --timeout=300s
kubectl -n "$NS" rollout status deployment/notifier --timeout=300s

echo "Waiting for Prometheus and Grafana..."
kubectl -n "$NS" rollout status deployment/prometheus --timeout=180s
kubectl -n "$NS" rollout status deployment/grafana --timeout=180s

kubectl -n "$NS" get pods
echo
echo "Deployed. Open it with (each in its own terminal):"
echo "  kubectl -n $NS port-forward service/api 8003:80          -> http://127.0.0.1:8003/docs"
echo "  kubectl -n $NS port-forward service/grafana 3005:3000    -> http://127.0.0.1:3005  (dashboards)"
echo "  kubectl -n $NS port-forward service/prometheus 9095:9090 -> http://127.0.0.1:9095  (raw metrics, alerts)"
