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
if kubectl -n "$NS" get httproute/grafana >/dev/null 2>&1; then
  c "grafana.$HOST" "$HTTPS" -o "$tmp/body" "https://grafana.$HOST:$HTTPS/api/health"
  grep -q '"database": *"ok"' "$tmp/body"
  echo "   ok: Grafana answers on grafana.$HOST"
else
  echo "   skipped: no Grafana in the lite setup"
fi

echo "4. A hostname with no route gets 404 from Envoy, never the API"
code=$(c unknown.localhost "$HTTPS" -k -o /dev/null -w '%{http_code}' "https://unknown.localhost:$HTTPS/health")
[[ "$code" == "404" ]] || { echo "   got: $code"; exit 1; }
echo "   ok: 404"

echo "5. The API sees the real client IP, and a forged X-Forwarded-For is ignored"
# From inside the cluster (a smoke-test pod) to the gateway's Service, claiming
# to be 6.6.6.6. The API must log the pod's real address instead. The pod
# prints its own IP so we know what to expect.
rid="gwcheck-$RANDOM$RANDOM"
image=$(kubectl -n "$NS" get deployment/worker -o jsonpath='{.spec.template.spec.containers[0].image}')
client_ip=$(kubectl -n "$NS" run "gwcheck-$RANDOM" --image="$image" --image-pull-policy=IfNotPresent \
  --restart=Never --labels=app.kubernetes.io/name=smoke-test --rm -i --quiet --command -- python -c "
import socket, ssl, urllib.request
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
req = urllib.request.Request('https://quickserve-gateway.envoy-gateway-system/health',
    headers={'Host': '$HOST', 'X-Request-ID': '$rid', 'X-Forwarded-For': '6.6.6.6'})
assert urllib.request.urlopen(req, context=ctx, timeout=5).status == 200
print(socket.gethostbyname(socket.gethostname()))")
line=
for _ in $(seq 1 10); do
  line=$(kubectl -n "$NS" logs -l app.kubernetes.io/name=api -c api --tail=500 | grep "$rid" || true)
  [[ -n "$line" ]] && break
  sleep 1
done
echo "   API log line: $line"
grep -q "\"client_ip\": \"$client_ip\"" <<<"$line" || { echo "   expected client_ip $client_ip (the test pod)"; exit 1; }
echo "   ok: same request ID in the API's log; client_ip is the test pod ($client_ip), not 6.6.6.6"

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

echo "7. The customer app (Phase 13) on the same hostname: / to the app, /api to the API"
headers=$(c "$HOST" "$HTTPS" -D - -o "$tmp/index.html" "https://$HOST:$HTTPS/orders/123")
grep -q '<div id="root">' "$tmp/index.html"
grep -qi '^content-security-policy: default-src' <<<"$headers"
grep -qi '^strict-transport-security: max-age=' <<<"$headers"
asset=$(grep -o '/assets/index-[^"]*\.js' "$tmp/index.html" | head -1)
cache=$(c "$HOST" "$HTTPS" -D - -o /dev/null "https://$HOST:$HTTPS$asset" | grep -i '^cache-control' || true)
grep -qi 'immutable' <<<"$cache" || { echo "   asset cache header: $cache"; exit 1; }
c "$HOST" "$HTTPS" "https://$HOST:$HTTPS/api/v1/pricing" | grep -q '"platform_fee"'
echo "   ok: the app's page (with CSP), its assets cached for a year, and /api still reaching the API"

echo "8. Tracing (Phase 15): Envoy starts the trace, the API continues it, Jaeger has both"
trace_id=$(c "$HOST" "$HTTPS" -D - -o /dev/null "https://$HOST:$HTTPS/api/v1/restaurants/near?lat=30.7333&lng=76.7794" \
  | tr -d '\r' | awk -F': ' 'tolower($1) == "x-trace-id" {print $2}')
[[ -n "$trace_id" ]] || { echo "   no X-Trace-Id header: is TRACING_ENABLED on?"; exit 1; }
found=
for _ in $(seq 1 30); do # the tail sampler waits 10 s for a trace to finish, then batches
  c "jaeger.$HOST" "$HTTPS" -o "$tmp/trace.json" "https://jaeger.$HOST:$HTTPS/api/traces/$trace_id" 2>/dev/null || true
  if found=$(python3 - "$tmp/trace.json" <<'PY'
import json, sys
try:
    t = json.load(open(sys.argv[1]))["data"][0]
except Exception:
    sys.exit(1)
services = sorted({p["serviceName"] for p in t["processes"].values()})
sql = sum(1 for s in t["spans"] if any(tag["key"] == "db.system.name" for tag in s.get("tags", [])))
if "quickserve-api" in services and len(services) >= 2 and sql:
    print(f"{len(t['spans'])} spans from {', '.join(services)}; {sql} SQL")
else:
    sys.exit(1)
PY
  ); then break; fi
  sleep 2
done
[[ -n "$found" ]] || { echo "   trace $trace_id never showed Envoy + API + SQL in Jaeger"; cat "$tmp/trace.json" | head -c 500; exit 1; }
echo "   ok: trace $trace_id: $found"

echo
echo "Front door OK."
