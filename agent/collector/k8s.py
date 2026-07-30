"""Collect pod status, events, and rollout history from the Kubernetes API.

Talks to the API server directly with httpx using the pod's service account
(no kubernetes client dependency). Outside a cluster, set KUBERNETES_API_URL
and optionally KUBERNETES_TOKEN for testing.
"""

import os
from pathlib import Path
from typing import Any

import httpx

SA_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")


def _api_base() -> str:
    if url := os.environ.get("KUBERNETES_API_URL"):
        return url
    host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    return f"https://{host}:{port}"


def _client() -> httpx.Client:
    headers = {}
    token = os.environ.get("KUBERNETES_TOKEN")
    if not token and (SA_DIR / "token").exists():
        token = (SA_DIR / "token").read_text().strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    ca = SA_DIR / "ca.crt"
    verify: bool | str = str(ca) if ca.exists() else False
    return httpx.Client(
        base_url=_api_base(), headers=headers, verify=verify, timeout=10.0
    )


def _get(path: str, params: dict | None = None) -> dict[str, Any]:
    with _client() as client:
        resp = client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()


def pod_status(namespace: str, pod: str) -> dict[str, Any]:
    data = _get(f"/api/v1/namespaces/{namespace}/pods/{pod}")
    status = data["status"]
    return {
        "phase": status.get("phase"),
        "container_statuses": status.get("containerStatuses", []),
        "node": data["spec"].get("nodeName"),
    }


def pod_events(namespace: str, pod: str, limit: int = 20) -> list[dict[str, Any]]:
    data = _get(
        f"/api/v1/namespaces/{namespace}/events",
        params={"fieldSelector": f"involvedObject.name={pod}", "limit": str(limit)},
    )
    return [
        {
            "type": e.get("type"),
            "reason": e.get("reason"),
            "message": e.get("message"),
            "count": e.get("count"),
            "lastTimestamp": e.get("lastTimestamp"),
        }
        for e in data.get("items", [])
    ]


def rollout_history(namespace: str, deployment: str) -> list[dict[str, Any]]:
    """Deployment revisions from its ReplicaSets (newest first)."""
    deploy = _get(f"/apis/apps/v1/namespaces/{namespace}/deployments/{deployment}")
    uid = deploy["metadata"]["uid"]
    replicasets = _get(f"/apis/apps/v1/namespaces/{namespace}/replicasets")
    revisions = []
    for rs in replicasets.get("items", []):
        owners = rs["metadata"].get("ownerReferences", [])
        if not any(o.get("uid") == uid for o in owners):
            continue
        containers = rs["spec"]["template"]["spec"]["containers"]
        revisions.append({
            "revision": int(
                rs["metadata"].get("annotations", {}).get(
                    "deployment.kubernetes.io/revision", 0
                )
            ),
            "images": [c["image"] for c in containers],
            "env": {
                c["name"]: c.get("env", []) for c in containers if c.get("env")
            },
            "replicas": rs["status"].get("replicas", 0),
        })
    return sorted(revisions, key=lambda r: r["revision"], reverse=True)


def collect(namespace: str, pod: str | None) -> dict[str, Any]:
    """Best-effort K8s context; individual lookup failures are recorded."""
    out: dict[str, Any] = {}
    if not pod:
        return {"error": "alert has no pod label"}
    for key, fn in (
        ("pod_status", lambda: pod_status(namespace, pod)),
        ("events", lambda: pod_events(namespace, pod)),
    ):
        try:
            out[key] = fn()
        except Exception as exc:  # noqa: BLE001 — context collection must not fail
            out[key] = {"error": str(exc)}
    # pod name -> deployment guess: strip the two hash suffixes
    parts = pod.rsplit("-", 2)
    if len(parts) == 3:
        try:
            out["rollout_history"] = rollout_history(namespace, parts[0])
        except Exception as exc:  # noqa: BLE001
            out["rollout_history"] = {"error": str(exc)}
    return out
