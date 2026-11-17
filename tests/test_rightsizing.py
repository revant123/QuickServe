"""The rightsizing report (infra/k8s/rightsizing.py): units, recommendations, cost."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "rightsizing", Path(__file__).resolve().parents[1] / "infra" / "k8s" / "rightsizing.py"
)
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)

MiB = 2**20


@pytest.mark.parametrize(("value", "millicores"), [("50m", 50), ("1", 1000), ("0.5", 500), (0, 0)])
def test_cpu_units(value, millicores):
    assert rs.cpu_m(value) == millicores


@pytest.mark.parametrize(
    ("value", "nbytes"), [("128Mi", 128 * MiB), ("1Gi", 2**30), ("512M", 512 * 10**6), ("1000", 1000), (0, 0)]
)
def test_memory_units(value, nbytes):
    assert rs.mem_bytes(value) == nbytes


def test_cpu_recommendation_is_p95_plus_headroom_rounded_up():
    assert rs.recommend_cpu_m(0.040) == 50  # 40m x 1.25 = 50m
    assert rs.recommend_cpu_m(0.041) == 55  # 51.25m -> next 5m step
    assert rs.recommend_cpu_m(0.001) == rs.MIN_CPU_M  # never below the floor


def test_memory_recommendation_is_peak_plus_headroom_rounded_up():
    assert rs.recommend_mem_mi(100 * MiB) == 128  # 125Mi -> next 16Mi step
    assert rs.recommend_mem_mi(10 * MiB) == rs.MIN_MEM_MI


def test_monthly_cost_of_a_request():
    # 1 vCPU + 1 GiB for 730 hours at the Fargate ARM prices.
    assert rs.monthly_usd(1000, 2**30) == pytest.approx(730 * (0.03238 + 0.00356))


def test_report_end_to_end(capsys):
    # Two API pods that each reserve 100m / 192Mi but use 8m / 70Mi.
    answers = {
        "quantile_over_time": {"api": 0.008},
        "max_over_time(quickserve:pod_cpu": {"api": 0.02},
        "max_over_time(quickserve:pod_memory": {"api": 70 * MiB},
        "count_over_time": {"api": 240},  # 240 samples x 15 s = 1 h
    }

    def prom(query):
        return next(v for k, v in answers.items() if k in query)

    rows = rs.report("1h", prom, {"api": (2, 100.0, 192.0 * MiB)})
    assert rows == [("api", 2, "100m", "8m", "20m", "10m", "192Mi", "70Mi", "96Mi")]
    out = capsys.readouterr().out
    assert "1.0 h of data" in out
    assert "Don't change the requests" in out  # an hour is too little to act on
    assert "(-83%)" in out  # far cheaper once sized to real use


def test_report_refuses_without_data():
    with pytest.raises(SystemExit, match="no usage data yet for: api"):
        rs.report("1h", lambda q: {}, {"api": (1, 50.0, 128.0 * MiB)})
