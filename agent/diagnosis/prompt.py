"""Build the structured diagnosis prompt from a collected alert context."""

import json
from typing import Any

SYSTEM_PROMPT = """\
You are the diagnosis engine of k8s-sentinel, an automated Kubernetes incident
responder. Given one firing alert and the diagnostic context collected for it
(Kubernetes state, Prometheus metrics, recent logs), determine the root cause
and recommend a remediation.

Rules for recommended_action:
- You may only recommend one of: restart_pod, scale_deployment,
  rollback_deployment, or none.
- Recommend rollback_deployment when a recent rollout (bad image, bad config)
  caused the failure; the rollout history shows the revisions.
- Recommend scale_deployment for capacity problems (e.g. sustained CPU
  throttling) that more replicas would relieve.
- Recommend restart_pod only when a restart plausibly clears the failure and
  the cause is not a bad revision or missing capacity.
- Recommend none for problems an application-level action cannot fix:
  node-level issues (disk pressure), failures of a *downstream* dependency
  (restarting the caller will not heal its dependency), or anything outside
  the whitelist. If the alert points at a downstream service being unhealthy,
  the remediation target would be that downstream service, not the alerting
  application — recommend none unless the downstream's own context shows a
  whitelisted fix for it.
- Set action_safe_to_automate=true only when the action is in the whitelist,
  clearly matches the root cause, and executing it automatically carries low
  risk. When in doubt, set it to false.

Ground every claim in the provided context: cite concrete observations
(event messages, metric values, log lines, revision numbers) in evidence.
If the context is too thin to be sure, say so in root_cause and lower
confidence accordingly."""

# Truncation limits keep the prompt focused (and bounded) — full data stays
# available to humans via the agent's /contexts endpoint.
MAX_LOG_LINES = 30
MAX_EVENTS = 10
MAX_REVISIONS = 5


def _truncated_context(context: dict[str, Any]) -> dict[str, Any]:
    slim = json.loads(json.dumps(context, default=str))  # deep copy, serializable

    loki = slim.get("loki", {})
    if isinstance(loki.get("lines"), list):
        loki["lines"] = loki["lines"][-MAX_LOG_LINES:]

    k8s = slim.get("kubernetes", {})
    if isinstance(k8s.get("events"), list):
        k8s["events"] = k8s["events"][-MAX_EVENTS:]
    if isinstance(k8s.get("rollout_history"), list):
        k8s["rollout_history"] = k8s["rollout_history"][:MAX_REVISIONS]

    return slim


def build_prompt(context: dict[str, Any]) -> str:
    slim = _truncated_context(context)
    alert = slim.get("alert", {})
    return (
        "Diagnose this Kubernetes alert.\n\n"
        f"## Alert\n{json.dumps(alert, indent=2)}\n\n"
        f"## Kubernetes state\n{json.dumps(slim.get('kubernetes'), indent=2)}\n\n"
        f"## Prometheus metrics\n{json.dumps(slim.get('prometheus'), indent=2)}\n\n"
        f"## Recent logs (Loki)\n{json.dumps(slim.get('loki'), indent=2)}\n"
    )
