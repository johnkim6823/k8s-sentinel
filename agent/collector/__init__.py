"""Context collection: gather Prometheus metrics, Loki logs, and K8s state
for one alert. Each source is best-effort — a failing source records its
error instead of failing the whole collection."""

from datetime import UTC, datetime
from typing import Any

from agent.collector import k8s, loki, prometheus
from agent.models import Alert


def collect_context(alert: Alert) -> dict[str, Any]:
    namespace, pod = alert.namespace, alert.pod
    context: dict[str, Any] = {
        "alert": {
            "name": alert.name,
            "status": alert.status,
            "labels": alert.labels,
            "annotations": alert.annotations,
            "startsAt": alert.startsAt.isoformat(),
        },
        "collected_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "kubernetes": k8s.collect(namespace, pod),
    }
    if pod:
        context["prometheus"] = prometheus.collect(namespace, pod)
        context["loki"] = loki.collect(namespace, pod)
    else:
        context["prometheus"] = {"skipped": "alert has no pod label"}
        context["loki"] = {"skipped": "alert has no pod label"}
    return context
