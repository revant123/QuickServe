#!/usr/bin/env bash
# End-to-end check of the front door (Phase 9), from OUTSIDE the cluster, the
# way a customer's phone would reach it. CI runs it; you can too:
#
#   infra/k8s/gateway_check.sh
#
# It opens its own port-forward on 18443/18081 (so it doesn't clash with one
# you already have on 8443) and closes it at the end.
set -euo pipefail

NS=quickserve
HTTPS=18443
HTTP=18081
HOST=quickserve.localhost
tmp=$(mktemp -d)
PF=
cleanup() { [[ -n "$PF" ]] && kill "$PF" 2>/dev/null; rm -rf "$tmp"; }
trap cleanup EXIT

# Trust exactly one certificate authority: QuickServe's own (cert-manager made it).
kubectl -n "$NS" get secret quickserve-ca -o jsonpath='{.data.ca\.crt}' | base64 -d > "$tmp/ca.crt"

kubectl -n envoy-gateway-system port-forward service/quickserve-gateway "$HTTPS:443" "$HTTP:80" >"$tmp/pf.log" 2>&1 &
PF=$!

# curl to a hostname, but connect to 127.0.0.1 (the port-forward). --resolve
# keeps the real hostname for TLS (SNI) and the Host header, which is what the
# Gateway routes on.
c() {
  local host=$1 port=$2
  shift 2
  curl -sS --max-time 10 --resolve "$host:$port:127.0.0.1" --cacert "$tmp/ca.crt" "$@"
}

for _ in $(seq 1 30); do
  c "$HOST" "$HTTPS" -o /dev/null "https://$HOST:$HTTPS/health" 2>/dev/null && break
  sleep 1
done

echo "1. HTTPS with a certificate signed by QuickServe's CA, routed to the API"
headers=$(c "$HOST" "$HTTPS" -D - -o "$tmp/body" "https://$HOST:$HTTPS/health/ready")
grep -q '"database":"ok"' "$tmp/body"
grep -qi '^strict-transport-security: max-age=' <<<"$headers"
grep -qi '^x-request-id: ' <<<"$headers"
echo "   ok: 200, HSTS header set, request ID returned"

echo "2. Plain HTTP is redirected to HTTPS"
location=$(c "$HOST" "$HTTP" -o /dev/null -w '%{http_code} %{redirect_url}' "http://$HOST:$HTTP/docs")
[[ "$location" == "301 https://$HOST"*/docs ]] || { echo "   got: $location"; exit 1; }
echo "   ok: $location"

echo "3. Another hostname, same Gateway: Grafana"
c "grafana.$HOST" "$HTTPS" -o "$tmp/body" "https://grafana.$HOST:$HTTPS/api/health"
grep -q '"database": *"ok"' "$tmp/body"
echo "   ok: Grafana answers on grafana.$HOST"

echo "4. A hostname with no route gets 404 from Envoy, never the API"
code=$(c unknown.localhost "$HTTPS" -k -o /dev/null -w '%{http_code}' "https://unknown.localhost:$HTTPS/health")
[[ "$code" == "404" ]] || { echo "   got: $code"; exit 1; }
echo "   ok: 404"

echo "5. The API sees the real client IP, and a forged X-Forwarded-For is ignored"
rid="gwcheck-$RANDOM$RANDOM"
c "$HOST" "$HTTPS" -o /dev/null -H "X-Request-ID: $rid" -H "X-Forwarded-For: 6.6.6.6" "https://$HOST:$HTTPS/health"
line=
for _ in $(seq 1 10); do
  line=$(kubectl -n "$NS" logs -l app.kubernetes.io/name=api --tail=500 --prefix=false | grep "$rid" || true)
  [[ -n "$line" ]] && break
  sleep 1
done
echo "   API log line: $line"
# Through a port-forward, Envoy's client is 127.0.0.1. Not 6.6.6.6 (forged)
# and not Envoy's own pod IP (10.244.x.x).
grep -q '"client_ip": "127.0.0.1"' <<<"$line"
echo "   ok: same request ID in the API's log, client_ip is the real client"

echo "6. The edge rate limit on /api/v1/auth/login (60 a minute)"
# GET, not POST: the API answers 405 at once, with no password hashing and no
# failed login counted. Envoy counts every request to the path either way.
limited=0
for _ in $(seq 1 75); do
  body=$(c "$HOST" "$HTTPS" "https://$HOST:$HTTPS/api/v1/auth/login" || true)
  if [[ "$body" == *local_rate_limited* ]]; then limited=$((limited + 1)); fi
done
(( limited > 0 )) || { echo "   no request was limited"; exit 1; }
echo "   ok: $limited of 75 requests were stopped by Envoy (429) before reaching the API"
echo "   (logins through the gateway are limited for the next minute)"

echo
echo "Front door OK."
