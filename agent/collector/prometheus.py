"""Collect metric context for an alert from the Prometheus HTTP API."""

import os
from typing import Any

import httpx

PROMETHEUS_URL = os.environ.get(
    "PROMETHEUS_URL",
    "http://monitoring-kube-prometheus-prometheus.monitoring:9090",
)

# Instant queries evaluated per target pod; {ns}/{pod} are formatted in.
POD_QUERIES: dict[str, str] = {
    "restarts_total": (
        'max by (container) (kube_pod_container_status_restarts_total'
        '{{namespace="{ns}", pod="{pod}"}})'
    ),
    "last_terminated_reason": (
        'kube_pod_container_status_last_terminated_reason'
        '{{namespace="{ns}", pod="{pod}"}} == 1'
    ),
    "waiting_reason": (
        'kube_pod_container_status_waiting_reason'
        '{{namespace="{ns}", pod="{pod}"}} == 1'
    ),
    "memory_working_set_bytes": (
        'max by (container) (container_memory_working_set_bytes'
        '{{namespace="{ns}", pod="{pod}", container!=""}})'
    ),
    "memory_limit_bytes": (
        'max by (container) (kube_pod_container_resource_limits'
        '{{namespace="{ns}", pod="{pod}", resource="memory"}})'
    ),
    "cpu_throttle_ratio_5m": (
        'sum by (container) (rate(container_cpu_cfs_throttled_periods_total'
        '{{namespace="{ns}", pod="{pod}", container!=""}}[5m]))'
        ' / sum by (container) (rate(container_cpu_cfs_periods_total'
        '{{namespace="{ns}", pod="{pod}", container!=""}}[5m]))'
    ),
}


def query(promql: str, timeout: float = 10.0) -> list[dict[str, Any]]:
    resp = httpx.get(
        f"{PROMETHEUS_URL}/api/v1/query", params={"query": promql}, timeout=timeout
    )
    resp.raise_for_status()
    return resp.json()["data"]["result"]


def collect(namespace: str, pod: str) -> dict[str, Any]:
    """Best-effort pod metric snapshot; individual query failures are recorded."""
    out: dict[str, Any] = {}
    for key, template in POD_QUERIES.items():
        promql = template.format(ns=namespace, pod=pod)
        try:
            out[key] = [
                {"labels": r["metric"], "value": r["value"][1]} for r in query(promql)
            ]
        except Exception as exc:  # noqa: BLE001 — context collection must not fail
            out[key] = {"error": str(exc)}
    return out
