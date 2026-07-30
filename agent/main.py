"""Sentinel Agent — FastAPI entrypoint.

Receives Alertmanager webhooks, validates them, and collects diagnostic
context (Prometheus metrics, Loki logs, K8s state) for each firing alert.
Diagnosis (Claude API) and remediation come in later milestones; for now the
collected context is logged as JSON and kept in memory for inspection via
GET /contexts.
"""

import json
import logging
from collections import deque
from typing import Any

from fastapi import BackgroundTasks, FastAPI

from agent.collector import collect_context
from agent.models import Alert, AlertmanagerWebhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sentinel")

app = FastAPI(title="k8s-sentinel agent")

# newest-last ring buffer of collected contexts (in-memory until Week 5 storage)
CONTEXTS: deque[dict[str, Any]] = deque(maxlen=50)


def process_alert(alert: Alert) -> None:
    log.info("collecting context for alert=%s pod=%s", alert.name, alert.pod)
    context = collect_context(alert)
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
    # collection can take seconds; ack Alertmanager immediately
    for alert in firing:
        background.add_task(process_alert, alert)
    return {"accepted": len(firing), "ignored_resolved": resolved}


@app.get("/contexts")
def contexts(limit: int = 10) -> list[dict[str, Any]]:
    return list(CONTEXTS)[-limit:]
