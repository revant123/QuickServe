#!/usr/bin/env bash
# Cluster add-ons QuickServe needs since Phase 9. deploy.sh runs this first;
# it's safe to run again (it skips what's already installed at this version).
#
#   Envoy Gateway  - the controller that turns Gateway + HTTPRoute objects into
#                    a running Envoy proxy. Also installs the Gateway API CRDs.
#   cert-manager   - creates TLS certificates and renews them before they expire.
#
# Pinned versions: an add-on upgrade is a change you test, not a surprise.
# Both are installed from their official release files on GitHub.
set -euo pipefail

ENVOY_GATEWAY_VERSION=v1.10.0 # bundles Gateway API v1.6.1
CERT_MANAGER_VERSION=v1.21.3

installed_image() { # namespace deployment -> its image, or nothing
  kubectl -n "$1" get deployment "$2" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || true
}

if [[ "$(installed_image envoy-gateway-system envoy-gateway)" != *":${ENVOY_GATEWAY_VERSION}" ]]; then
  echo "Installing Envoy Gateway ${ENVOY_GATEWAY_VERSION} (and the Gateway API CRDs)..."
  # --server-side: the CRDs are too big for the annotation a normal apply writes.
  kubectl apply --server-side --force-conflicts \
    -f "https://github.com/envoyproxy/gateway/releases/download/${ENVOY_GATEWAY_VERSION}/install.yaml"
fi

if [[ "$(installed_image cert-manager cert-manager)" != *":${CERT_MANAGER_VERSION}" ]]; then
  echo "Installing cert-manager ${CERT_MANAGER_VERSION}..."
  kubectl apply --server-side --force-conflicts \
    -f "https://github.com/cert-manager/cert-manager/releases/download/${CERT_MANAGER_VERSION}/cert-manager.yaml"
fi

echo "Waiting for Envoy Gateway and cert-manager..."
kubectl -n envoy-gateway-system rollout status deployment/envoy-gateway --timeout=300s
for d in cert-manager cert-manager-cainjector cert-manager-webhook; do
  kubectl -n cert-manager rollout status "deployment/$d" --timeout=300s
done
