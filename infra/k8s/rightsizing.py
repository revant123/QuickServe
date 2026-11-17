"""Rightsizing report: what each QuickServe pod RESERVES vs what it really USES.

    python3 infra/k8s/rightsizing.py               # the last hour
    python3 infra/k8s/rightsizing.py --window 7d   # a week: the honest window

Standard library only. It runs on your machine and needs nothing but kubectl:
the requests come from `kubectl get deployments`, the usage from Prometheus,
reached through the Kubernetes API server (no port-forward needed).

Why it matters. A pod's *request* is capacity the scheduler sets aside for it,
used or not. Bills follow requests: Fargate and GKE Autopilot charge for what
a pod requests, and on your own nodes over-asking means buying more nodes.

How it recommends:
  CPU     p95 of usage x 1.25 headroom. CPU is "compressible": a pod that needs
          more than its request just shares or waits, it doesn't crash.
  memory  PEAK usage x 1.25 headroom. Memory is not compressible: a pod over its
          memory limit is killed (OOMKilled), so size for the worst moment.

It only prints. Change requests in infra/k8s/base/*.yaml (the files are the
source of truth: `kubectl set resources` would be undone by the next deploy).
"""

import argparse
import json
import math
import subprocess
import sys
import urllib.parse
import urllib.request

NS = "quickserve"
APPS = ("api", "worker", "notifier")  # the pods that export process metrics
HEADROOM = 1.25
MIN_CPU_M = 10  # millicores; below this the numbers are noise
MIN_MEM_MI = 64  # MiB; a Python process needs about this just to start
HOURS_PER_MONTH = 730
# A price for a REQUEST: AWS Fargate, Linux/ARM (Graviton, like our t4g
# machines), us-east-1. Fargate bills the vCPU and memory a task asks for.
USD_PER_VCPU_HOUR = 0.03238
USD_PER_GB_HOUR = 0.00356


# ----- units -----


def cpu_m(value):
    """Kubernetes CPU quantity -> millicores. '50m' -> 50, '1' -> 1000, '0.5' -> 500."""
    value = str(value)
    if value.endswith("m"):
        return float(value[:-1])
    return float(value) * 1000


_MEM_UNITS = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40, "k": 10**3, "M": 10**6, "G": 10**9, "T": 10**12}


def mem_bytes(value):
    """Kubernetes memory quantity -> bytes. '128Mi' -> 134217728, '1G' -> 10**9."""
    value = str(value)
    for suffix in sorted(_MEM_UNITS, key=len, reverse=True):
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * _MEM_UNITS[suffix]
    return float(value)


def recommend_cpu_m(p95_cores):
    """p95 usage in cores -> request in millicores, rounded up to 5m."""
    return max(MIN_CPU_M, math.ceil(p95_cores * 1000 * HEADROOM / 5) * 5)


def recommend_mem_mi(peak_bytes):
    """Peak usage in bytes -> request in MiB, rounded up to 16Mi."""
    return max(MIN_MEM_MI, math.ceil(peak_bytes / 2**20 * HEADROOM / 16) * 16)


def monthly_usd(cpu_millicores, memory_bytes):
    """What a request costs per month if you pay per request (Fargate prices)."""
    return HOURS_PER_MONTH * (cpu_millicores / 1000 * USD_PER_VCPU_HOUR + memory_bytes / 2**30 * USD_PER_GB_HOUR)


# ----- data -----


def kubectl(*args):
    return subprocess.run(["kubectl", *args], check=True, capture_output=True, text=True).stdout


def requests_per_pod():
    """{app: (replicas, cpu millicores, memory bytes)} from the live Deployments.

    Init containers are left out: they finish before the app starts, so they
    don't hold their request while the pod runs.
    """
    out = {}
    for d in json.loads(kubectl("-n", NS, "get", "deployments", "-o", "json"))["items"]:
        app = d["metadata"]["name"]
        if app not in APPS:
            continue
        cpu = mem = 0.0
        for c in d["spec"]["template"]["spec"]["containers"]:
            req = c.get("resources", {}).get("requests", {})
            cpu += cpu_m(req.get("cpu", 0))
            mem += mem_bytes(req.get("memory", 0))
        replicas = d.get("status", {}).get("replicas") or d["spec"].get("replicas", 1)
        out[app] = (replicas, cpu, mem)
    return out


def make_prom(base_url):
    """A function that runs one PromQL query and returns {app: value}."""

    def fetch(query):
        path = "/api/v1/query?" + urllib.parse.urlencode({"query": query})
        if base_url:
            with urllib.request.urlopen(base_url.rstrip("/") + path, timeout=10) as resp:
                body = resp.read()
        else:  # through the API server's service proxy
            body = kubectl("get", "--raw", f"/api/v1/namespaces/{NS}/services/prometheus:web/proxy{path}")
        data = json.loads(body)["data"]["result"]
        return {r["metric"].get("app", ""): float(r["value"][1]) for r in data}

    return fetch


def report(window, prom, requests):
    p95 = prom(f"max by (app) (quantile_over_time(0.95, quickserve:pod_cpu_cores:rate5m[{window}]))")
    cpu_peak = prom(f"max by (app) (max_over_time(quickserve:pod_cpu_cores:rate5m[{window}]))")
    mem_peak = prom(f"max by (app) (max_over_time(quickserve:pod_memory_bytes[{window}]))")
    # How much history there really is (one sample per 15 s rule evaluation).
    samples = prom(f"max by (app) (count_over_time(quickserve:pod_memory_bytes[{window}]))")

    missing = [a for a in requests if a not in mem_peak or a not in p95]
    if missing:
        sys.exit(f"Prometheus has no usage data yet for: {', '.join(missing)}. Wait a few minutes and retry.")

    rows, now_cost, new_cost = [], 0.0, 0.0
    reserved_cpu = used_cpu = reserved_mem = used_mem = 0.0
    for app in sorted(requests):
        replicas, cpu_req, mem_req = requests[app]
        rec_cpu = recommend_cpu_m(p95[app])
        rec_mem = recommend_mem_mi(mem_peak[app])
        rows.append(
            (
                app,
                replicas,
                f"{cpu_req:.0f}m",
                f"{p95[app] * 1000:.0f}m",
                f"{cpu_peak[app] * 1000:.0f}m",
                f"{rec_cpu}m",
                f"{mem_req / 2**20:.0f}Mi",
                f"{mem_peak[app] / 2**20:.0f}Mi",
                f"{rec_mem}Mi",
            )
        )
        now_cost += replicas * monthly_usd(cpu_req, mem_req)
        new_cost += replicas * monthly_usd(rec_cpu, rec_mem * 2**20)
        reserved_cpu += replicas * cpu_req
        used_cpu += replicas * p95[app] * 1000
        reserved_mem += replicas * mem_req
        used_mem += replicas * mem_peak[app]

    hours = max(samples.values()) * 15 / 3600
    header = ("app", "pods", "CPU req", "CPU p95", "CPU peak", "-> CPU", "MEM req", "MEM peak", "-> MEM")
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    print(f"Usage over the last {window} ({hours:.1f} h of data). Requests and usage are PER POD.\n")
    for r in [header, *rows]:
        cells = [str(v).rjust(w) for v, w in zip(r, widths, strict=True)]
        cells[0] = str(r[0]).ljust(widths[0])  # app names read better on the left
        print("  ".join(cells))

    print(
        f"\nReserved but unused (all pods): {(reserved_cpu - used_cpu) / 1000:.2f} vCPU of "
        f"{reserved_cpu / 1000:.2f}, {(reserved_mem - used_mem) / 2**30:.2f} GiB of {reserved_mem / 2**30:.2f}."
    )
    if now_cost:
        print(
            f"Priced per request (AWS Fargate, ARM, us-east-1): ${now_cost:.2f}/month now, "
            f"${new_cost:.2f}/month with the recommended requests "
            f"({new_cost / now_cost - 1:+.0%})."
        )
    if hours < 24:
        print(
            f"\nOnly {hours:.1f} h of data, probably with almost no traffic. Don't change the requests"
            "\nfrom this: size from at least a week that includes your busiest hour (dinner rush)."
        )
    print("\nTo apply a recommendation, edit `requests:` in infra/k8s/base/<app>.yaml and deploy.")
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--window", default="1h", help="how far back to look: 1h, 24h, 7d (default 1h)")
    ap.add_argument("--prometheus", help="Prometheus URL, e.g. http://127.0.0.1:9095 (default: via kubectl)")
    args = ap.parse_args()
    report(args.window, make_prom(args.prometheus), requests_per_pod())


if __name__ == "__main__":
    main()
