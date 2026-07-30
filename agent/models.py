"""Pydantic models for the Alertmanager webhook payload.

Schema reference: https://prometheus.io/docs/alerting/latest/configuration/#webhook_config
"""

from datetime import datetime

from pydantic import BaseModel


class Alert(BaseModel):
    status: str  # "firing" | "resolved"
    labels: dict[str, str]
    annotations: dict[str, str] = {}
    startsAt: datetime
    endsAt: datetime | None = None
    generatorURL: str = ""
    fingerprint: str = ""

    @property
    def name(self) -> str:
        return self.labels.get("alertname", "unknown")

    @property
    def namespace(self) -> str:
        return self.labels.get("namespace", "default")

    @property
    def pod(self) -> str | None:
        return self.labels.get("pod")


class AlertmanagerWebhook(BaseModel):
    version: str = "4"
    groupKey: str = ""
    status: str
    receiver: str = ""
    groupLabels: dict[str, str] = {}
    commonLabels: dict[str, str] = {}
    commonAnnotations: dict[str, str] = {}
    externalURL: str = ""
    alerts: list[Alert]
