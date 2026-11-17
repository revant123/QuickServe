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

kubectl apply -k "$OVERLAY"

echo "Waiting for PostgreSQL and Redis..."
kubectl -n "$NS" rollout status statefulset/postgres --timeout=180s
kubectl -n "$NS" rollout status deployment/redis --timeout=120s

echo "Waiting for the migration Job..."
kubectl -n "$NS" wait --for=condition=complete job/migrate --timeout=300s

echo "Waiting for the API and the worker..."
kubectl -n "$NS" rollout status deployment/api --timeout=300s
kubectl -n "$NS" rollout status deployment/worker --timeout=300s

kubectl -n "$NS" get pods
echo
echo "Deployed. Open it with:"
echo "  kubectl -n $NS port-forward service/api 8003:80"
echo "  then http://127.0.0.1:8003/docs"
