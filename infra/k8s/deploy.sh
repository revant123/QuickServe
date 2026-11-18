#!/usr/bin/env bash
# Deploy QuickServe to the current Kubernetes cluster, in the right order.
#
#   infra/k8s/deploy.sh                       # minikube: deploys the image of the commit you have checked out
#   IMAGE_TAG=main infra/k8s/deploy.sh        # ...or whatever `main` points to right now
#   infra/k8s/deploy.sh infra/k8s/overlays/ci # what CI uses (an image built in the job)
#
# Order: database and Redis -> migration Job -> API and worker. The API and
# worker pods also wait for the migration themselves (init containers), so the
# order holds even if someone runs `kubectl apply` by hand.
set -euo pipefail

OVERLAY="${1:-infra/k8s/overlays/local}"
NS=quickserve
REPO=revant123/quickserve

# Is this tag published on ghcr.io? (Public package: an anonymous token is enough.)
image_exists() {
  local token
  token=$(curl -fsS "https://ghcr.io/token?scope=repository:${REPO}:pull" | sed -E 's/.*"token":"([^"]+)".*/\1/')
  curl -fsS -o /dev/null -H "Authorization: Bearer ${token}" \
    -H "Accept: application/vnd.oci.image.index.v1+json" \
    "https://ghcr.io/v2/${REPO}/manifests/$1"
}

if [[ "$OVERLAY" != *ci* ]]; then
  # Deploy EXACTLY the commit you have checked out: its immutable sha- tag,
  # not the moving `main` tag. Right after a merge, `main` on ghcr.io still
  # points to the PREVIOUS build until CI finishes publishing (~3-5 minutes),
  # so "deploy main" would silently run old code. A sha tag can't be stale:
  # it either exists or it doesn't.
  TAG="${IMAGE_TAG:-sha-$(git rev-parse HEAD | cut -c1-7)}"
  if [[ -n "$(git status --porcelain -- app migrations scripts)" ]]; then
    echo "Note: you have uncommitted changes in app/, migrations/ or scripts/. They are NOT in the image."
  fi
  if [[ -z "${IMAGE_TAG:-}" ]] && ! git merge-base --is-ancestor HEAD origin/main 2>/dev/null; then
    echo "Your checked-out commit isn't on main (are you on a feature branch?). CI only publishes"
    echo "images for main, so there is no image for it. Run: git checkout main && git pull"
    echo "or deploy the newest main build: IMAGE_TAG=main infra/k8s/deploy.sh"
    exit 1
  fi
  waited=0
  until image_exists "$TAG"; do
    if (( waited >= ${WAIT_MINUTES:-10} * 60 )); then
      echo "ghcr.io/${REPO}:${TAG} still isn't published after ${WAIT_MINUTES:-10} minutes."
      echo "CI publishes images only for commits on main. Check the 'publish' job on GitHub Actions,"
      echo "or deploy the newest main build instead: IMAGE_TAG=main infra/k8s/deploy.sh"
      exit 1
    fi
    echo "Waiting for CI to publish ghcr.io/${REPO}:${TAG} (checked ${waited}s so far)..."
    sleep 20
    waited=$((waited + 20))
  done
  echo "Deploying ghcr.io/${REPO}:${TAG}"

  # Render the overlay and swap the tag. (Kustomize can't take the tag from a
  # variable, and an overlay can't point at an absolute path, so a one-line
  # substitution on the rendered YAML is the simplest honest way.)
  render() { kubectl kustomize "$OVERLAY" | sed "s#ghcr.io/${REPO}:main#ghcr.io/${REPO}:${TAG}#g"; }
fi

# Cluster add-ons the manifests need (Phase 9): Envoy Gateway and cert-manager.
"$(dirname "$0")/addons.sh"

# A Job's pod spec can't change after it's created. Delete last deploy's Job so
# this deploy's image runs its migrations.
kubectl -n "$NS" delete job migrate --ignore-not-found --wait=true >/dev/null 2>&1 || true

# Was QuickServe already running before this deploy?
ALREADY_DEPLOYED=$(kubectl -n "$NS" get deployment api -o name 2>/dev/null || true)

apply_manifests() {
  if [[ "$OVERLAY" != *ci* ]]; then
    render | kubectl apply -f -
  else
    kubectl apply -k "$OVERLAY"
  fi
}
# Retried: on a fresh cluster cert-manager's webhook can report "ready" a few
# seconds before it accepts requests, so the first try at the certificates fails.
for attempt in 1 2 3 4 5 6; do
  if apply_manifests; then break; fi
  if (( attempt == 6 )); then echo "kubectl apply kept failing"; exit 1; fi
  echo "Apply failed (attempt $attempt); retrying in 10 s..."
  sleep 10
done

echo "Waiting for PostgreSQL and Redis..."
kubectl -n "$NS" rollout status statefulset/postgres --timeout=180s
kubectl -n "$NS" rollout status deployment/redis --timeout=120s

echo "Waiting for the migration Job..."
kubectl -n "$NS" wait --for=condition=complete job/migrate --timeout=300s

# A new sha- tag is a change in the YAML, so Kubernetes rolls the pods by itself;
# the same sha- tag means nothing changed, and nothing should restart. Only the
# moving `main` tag (IMAGE_TAG=main) needs a restart to fetch a newer build.
if [[ -n "$ALREADY_DEPLOYED" && "${TAG:-}" == "main" ]]; then
  echo "Restarting the API and worker to pick up the newest image..."
  kubectl -n "$NS" rollout restart deployment/api deployment/worker deployment/notifier
fi

echo "Waiting for the API, the worker and the notifier..."
kubectl -n "$NS" rollout status deployment/api --timeout=300s
kubectl -n "$NS" rollout status deployment/worker --timeout=300s
kubectl -n "$NS" rollout status deployment/notifier --timeout=300s

echo "Waiting for Prometheus, Grafana, Alertmanager and Mailpit..."
kubectl -n "$NS" rollout status deployment/prometheus --timeout=180s
kubectl -n "$NS" rollout status deployment/grafana --timeout=180s
kubectl -n "$NS" rollout status deployment/alertmanager --timeout=120s
kubectl -n "$NS" rollout status deployment/mailpit --timeout=120s

echo "Waiting for the HTTPS certificate and the gateway (Envoy)..."
kubectl -n "$NS" wait --for=condition=Ready certificate/quickserve-tls --timeout=180s
kubectl -n "$NS" wait --for=condition=Programmed gateway/quickserve --timeout=180s
for _ in $(seq 1 30); do # Envoy Gateway creates the Deployment a moment after the Gateway
  kubectl -n envoy-gateway-system get deployment/quickserve-gateway >/dev/null 2>&1 && break
  sleep 2
done
kubectl -n envoy-gateway-system rollout status deployment/quickserve-gateway --timeout=180s

kubectl -n "$NS" get pods
echo
echo "Deployed. The front door (Phase 9), in its own terminal:"
echo "  kubectl -n envoy-gateway-system port-forward service/quickserve-gateway 8443:443"
echo "  -> https://quickserve.localhost:8443/docs   and   https://grafana.quickserve.localhost:8443"
echo "     (the browser warns about the certificate until you trust QuickServe's local CA: see the README)"
echo
echo "Or each service directly (each in its own terminal):"
echo "  kubectl -n $NS port-forward service/api 8003:80          -> http://127.0.0.1:8003/docs"
echo "  kubectl -n $NS port-forward service/grafana 3005:3000    -> http://127.0.0.1:3005  (dashboards)"
echo "  kubectl -n $NS port-forward service/prometheus 9095:9090 -> http://127.0.0.1:9095  (raw metrics, alerts)"
echo "  kubectl -n $NS port-forward service/alertmanager 9096:9093 -> http://127.0.0.1:9096 (grouped alerts, silences)"
echo "  kubectl -n $NS port-forward service/mailpit 8026:8025    -> http://127.0.0.1:8026  (the alert emails)"
echo
echo "Checks you can run any time:"
echo "  infra/k8s/gateway_check.sh   # HTTPS, routing, real client IP, edge rate limit"
echo "  infra/k8s/netpol_check.sh    # network policies are really enforced (needs --cni=calico on minikube)"
echo
echo "FinOps: what the pods reserve vs what they use:"
echo "  python3 infra/k8s/rightsizing.py"
