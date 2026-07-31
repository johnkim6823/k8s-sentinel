"""Remediation executor with safety gates (CLAUDE.md 안전 규칙).

Only three whitelisted actions are allowed: restart_pod, scale_deployment,
rollback_deployment. Every action follows: build dry-run -> require approval
-> execute -> verify the alert cleared. Scenarios 5 (node disk pressure) and
6 (downstream failure) are hard-excluded from automation regardless of what
the diagnosis recommends.
"""

import os
import time
from typing import Any

import httpx

from agent import k8s_client

WHITELIST = {"restart_pod", "scale_deployment", "rollback_deployment"}

# Scenarios excluded from automation by design; matched on the alert's
# `scenario` label so a mislabeled diagnosis can't bypass the guard.
NON_AUTOMATABLE_SCENARIOS = {"node-disk-pressure", "downstream-failure"}


class RemediationError(Exception):
    """A remediation action could not be planned or executed."""


class NotAutomatable(RemediationError):
    """The action is excluded from automation by the safety rules."""


def _deployment_for_pod(pod: str) -> str:
    """Best-effort deployment name from a pod name (strip the two hash suffixes)."""
    parts = pod.rsplit("-", 2)
    return parts[0] if len(parts) == 3 else pod


def plan(
    action: str, namespace: str, target: str, scenario: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate an action and return its dry-run description without executing."""
    params = params or {}
    if action not in WHITELIST:
        raise RemediationError(
            f"action {action!r} is not in the whitelist {sorted(WHITELIST)}"
        )
    if scenario in NON_AUTOMATABLE_SCENARIOS:
        raise NotAutomatable(
            f"scenario {scenario!r} is excluded from automated remediation"
        )

    if action == "restart_pod":
        deployment = _deployment_for_pod(target)
        return {
            "action": action,
            "namespace": namespace,
            "target": deployment,
            "operation": f"rollout restart deployment/{deployment}",
            "params": {},
        }
    if action == "scale_deployment":
        replicas = int(params.get("replicas", 2))
        return {
            "action": action,
            "namespace": namespace,
            "target": target,
            "operation": f"scale deployment/{target} to {replicas} replicas",
            "params": {"replicas": replicas},
        }
    # rollback_deployment
    return {
        "action": action,
        "namespace": namespace,
        "target": target,
        "operation": f"rollback deployment/{target} to previous revision",
        "params": {},
    }


def execute(dry_run: dict[str, Any]) -> dict[str, Any]:
    """Execute a previously-planned (and approved) action."""
    action = dry_run["action"]
    namespace = dry_run["namespace"]
    target = dry_run["target"]
    if action == "restart_pod":
        return _restart(namespace, target)
    if action == "scale_deployment":
        return _scale(namespace, target, dry_run["params"]["replicas"])
    if action == "rollback_deployment":
        return _rollback(namespace, target)
    raise RemediationError(f"unknown action {action!r}")


def _restart(namespace: str, deployment: str) -> dict[str, Any]:
    # Same mechanism as `kubectl rollout restart`: bump a restartedAt annotation.
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    body = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {"sentinel.k8s/restartedAt": ts}
                }
            }
        }
    }
    k8s_client.patch(
        f"/apis/apps/v1/namespaces/{namespace}/deployments/{deployment}",
        body, "application/strategic-merge-patch+json",
    )
    return {"restarted": deployment, "at": ts}


def _scale(namespace: str, deployment: str, replicas: int) -> dict[str, Any]:
    k8s_client.patch(
        f"/apis/apps/v1/namespaces/{namespace}/deployments/{deployment}/scale",
        {"spec": {"replicas": replicas}}, "application/merge-patch+json",
    )
    return {"scaled": deployment, "replicas": replicas}


def _rollback(namespace: str, deployment: str) -> dict[str, Any]:
    """Roll a Deployment back to its previous revision.

    Finds the ReplicaSet one revision behind the current one and re-applies its
    pod template — the same effect as `kubectl rollout undo`.
    """
    base = f"/apis/apps/v1/namespaces/{namespace}"
    deploy = k8s_client.get(f"{base}/deployments/{deployment}")
    uid = deploy["metadata"]["uid"]
    current_rev = int(
        deploy["metadata"].get("annotations", {}).get(
            "deployment.kubernetes.io/revision", 0
        )
    )
    replicasets = k8s_client.get(f"{base}/replicasets")
    owned = [
        rs for rs in replicasets.get("items", [])
        if any(o.get("uid") == uid for o in rs["metadata"].get("ownerReferences", []))
    ]
    revs = {
        int(rs["metadata"].get("annotations", {}).get(
            "deployment.kubernetes.io/revision", 0)): rs
        for rs in owned
    }
    prior = [r for r in sorted(revs) if r < current_rev]
    if not prior:
        raise RemediationError(f"no prior revision to roll {deployment} back to")
    target_rs = revs[prior[-1]]
    template = target_rs["spec"]["template"]
    k8s_client.patch(
        f"{base}/deployments/{deployment}",
        {"spec": {"template": template}}, "application/strategic-merge-patch+json",
    )
    return {"rolled_back": deployment, "from_revision": current_rev, "to_revision": prior[-1]}


def deployment_ready(namespace: str, deployment: str) -> bool:
    data = k8s_client.get(f"/apis/apps/v1/namespaces/{namespace}/deployments/{deployment}")
    status = data.get("status", {})
    desired = data["spec"].get("replicas", 1)
    return (
        status.get("readyReplicas", 0) == desired
        and status.get("updatedReplicas", 0) == desired
        and status.get("unavailableReplicas", 0) == 0
    )


def verify_alert_cleared(
    alert_name: str, timeout_s: int = 300, poll_s: int = 5
) -> bool:
    """Poll Prometheus until the alert is absent (resolved), or time out.

    N분 후 알람 해소 검증 (CLAUDE.md). Prometheus URL comes from PROMETHEUS_URL.
    """
    url = os.environ.get(
        "PROMETHEUS_URL",
        "http://monitoring-kube-prometheus-prometheus.monitoring:9090",
    )
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{url}/api/v1/alerts", timeout=10.0)
            resp.raise_for_status()
            alerts = resp.json()["data"]["alerts"]
            if not any(a["labels"].get("alertname") == alert_name for a in alerts):
                return True
        except Exception:  # noqa: BLE001 — keep polling on transient errors
            pass
        time.sleep(poll_s)
    return False
