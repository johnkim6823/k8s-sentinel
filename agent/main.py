"""Sentinel Agent — FastAPI entrypoint.

Full pipeline: receive an Alertmanager webhook -> collect diagnostic context
(Prometheus, Loki, K8s) -> diagnose with Claude -> plan a whitelisted
remediation (dry-run) -> approval gate -> execute -> verify the alert cleared,
recording every remediation to SQLite and reporting to Slack.

The approval gate is real: a planned remediation sits in `requested` until it
is approved via POST /remediations/{id}/approve (or auto-approved when
AUTO_APPROVE=1 for demos). Scenarios 5 and 6 are hard-excluded from automation.
"""

import json
import logging
import os
from collections import deque
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from agent import diagnosis
from agent.collector import collect_context
from agent.models import Alert, AlertmanagerWebhook
from agent.remediation import executor
from agent.reporter import slack
from agent.storage import history

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sentinel")

app = FastAPI(title="k8s-sentinel agent")

CONTEXTS: deque[dict[str, Any]] = deque(maxlen=50)

AUTO_APPROVE = os.environ.get("AUTO_APPROVE") == "1"


def _plan_remediation(alert: Alert, diag: dict[str, Any]) -> int | None:
    """Plan a remediation from a diagnosis and record it as `requested`.

    Returns the remediation id, or None when no action should be taken.
    """
    action = diag.get("recommended_action")
    if action == "none" or action not in executor.WHITELIST:
        return None
    if not diag.get("action_safe_to_automate"):
        log.info("diagnosis marked action %s not safe to automate; skipping", action)
        return None

    scenario = alert.labels.get("scenario")
    try:
        dry_run = executor.plan(action, alert.namespace, alert.pod or "", scenario)
    except executor.RemediationError as exc:
        log.warning("remediation not planned: %s", exc)
        return None

    rid = history.record_request(
        alert_name=alert.name, namespace=alert.namespace,
        target=dry_run["target"], action=action,
        params=dry_run["params"], dry_run=dry_run,
    )
    log.info("remediation #%d planned (requested): %s", rid, dry_run["operation"])
    return rid


def run_remediation(remediation_id: int) -> dict[str, Any]:
    """Execute an approved remediation, verify it, and record the outcome."""
    rec = history.get(remediation_id)
    if rec is None:
        raise executor.RemediationError(f"remediation #{remediation_id} not found")
    dry_run = rec["dry_run"]
    try:
        result = executor.execute(dry_run)
    except Exception as exc:  # noqa: BLE001
        history.update_status(remediation_id, "failed", result={"error": str(exc)},
                              executed=True)
        slack.report_remediation(rec["alert_name"], rec["action"], "failed",
                                 {"error": str(exc)})
        log.error("remediation #%d failed: %s", remediation_id, exc)
        return {"status": "failed", "error": str(exc)}

    history.update_status(remediation_id, "executed", result=result, executed=True)
    log.info("remediation #%d executed: %s", remediation_id, result)

    cleared = executor.verify_alert_cleared(rec["alert_name"])
    status = "verified" if cleared else "executed"
    history.update_status(remediation_id, status, result=result, verified=cleared)
    slack.report_remediation(rec["alert_name"], rec["action"], status, result)
    log.info("remediation #%d %s (alert cleared=%s)", remediation_id, status, cleared)
    return {"status": status, "result": result, "alert_cleared": cleared}


def process_alert(alert: Alert) -> None:
    log.info("collecting context for alert=%s pod=%s", alert.name, alert.pod)
    context = collect_context(alert)

    if diagnosis.enabled():
        try:
            result = diagnosis.diagnose(context)
            context["diagnosis"] = result.model_dump()
            log.info(
                "diagnosis: action=%s safe=%s confidence=%.2f",
                result.recommended_action, result.action_safe_to_automate,
                result.confidence,
            )
        except diagnosis.DiagnosisError as exc:
            context["diagnosis"] = {"error": str(exc)}
            log.error("diagnosis failed: %s", exc)
    else:
        context["diagnosis"] = {"skipped": "ANTHROPIC_API_KEY not configured"}
        log.info("diagnosis skipped: ANTHROPIC_API_KEY not configured")

    slack.report_diagnosis(alert.name, context["diagnosis"])

    rid = _plan_remediation(alert, context["diagnosis"])
    if rid is not None:
        context["remediation_id"] = rid
        if AUTO_APPROVE:
            log.info("AUTO_APPROVE set; approving remediation #%d", rid)
            history.update_status(rid, "approved")
            run_remediation(rid)

    CONTEXTS.append(context)
    log.info("context collected: %s", json.dumps(context, default=str))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/webhook")
def webhook(payload: AlertmanagerWebhook, background: BackgroundTasks) -> dict:
    firing = [a for a in payload.alerts if a.status == "firing"]
    resolved = len(payload.alerts) - len(firing)
    log.info(
        "webhook received: receiver=%s firing=%d resolved=%d",
        payload.receiver, len(firing), resolved,
    )
    for alert in firing:
        background.add_task(process_alert, alert)
    return {"accepted": len(firing), "ignored_resolved": resolved}


@app.get("/contexts")
def contexts(limit: int = 10) -> list[dict[str, Any]]:
    return list(CONTEXTS)[-limit:]


@app.get("/remediations")
def remediations(limit: int = 20) -> list[dict[str, Any]]:
    return history.list_recent(limit)


@app.get("/remediations/{remediation_id}")
def remediation(remediation_id: int) -> dict[str, Any]:
    rec = history.get(remediation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="remediation not found")
    return rec


@app.post("/remediations/{remediation_id}/approve")
def approve(remediation_id: int, background: BackgroundTasks) -> dict[str, Any]:
    rec = history.get(remediation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="remediation not found")
    if rec["status"] != "requested":
        raise HTTPException(
            status_code=409,
            detail=f"remediation #{remediation_id} is {rec['status']}, not requested",
        )
    history.update_status(remediation_id, "approved")
    background.add_task(run_remediation, remediation_id)
    return {"remediation_id": remediation_id, "status": "approved"}


@app.post("/remediations/{remediation_id}/reject")
def reject(remediation_id: int) -> dict[str, Any]:
    rec = history.get(remediation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="remediation not found")
    if rec["status"] != "requested":
        raise HTTPException(
            status_code=409,
            detail=f"remediation #{remediation_id} is {rec['status']}, not requested",
        )
    history.update_status(remediation_id, "rejected")
    slack.report_remediation(rec["alert_name"], rec["action"], "rejected")
    return {"remediation_id": remediation_id, "status": "rejected"}


class ManualRemediation(BaseModel):
    """Body for POST /remediate — lets an operator plan an action directly,
    without waiting for the LLM (useful when no API key is configured)."""

    action: str
    namespace: str = "default"
    target: str
    alert_name: str = "manual"
    scenario: str | None = None
    params: dict[str, Any] = {}


@app.post("/remediate")
def remediate(req: ManualRemediation) -> dict[str, Any]:
    try:
        dry_run = executor.plan(
            req.action, req.namespace, req.target, req.scenario, req.params
        )
    except executor.RemediationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rid = history.record_request(
        alert_name=req.alert_name, namespace=req.namespace,
        target=dry_run["target"], action=req.action,
        params=dry_run["params"], dry_run=dry_run,
    )
    return {"remediation_id": rid, "status": "requested", "dry_run": dry_run}
