"""Collect pod status, events, and rollout history from the Kubernetes API.

Talks to the API server directly via the shared agent.k8s_client (no
kubernetes-client dependency). Outside a cluster, set KUBERNETES_API_URL and
optionally KUBERNETES_TOKEN for testing.
"""

from typing import Any

from agent import k8s_client


def _get(path: str, params: dict | None = None) -> dict[str, Any]:
    return k8s_client.get(path, params=params)


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
