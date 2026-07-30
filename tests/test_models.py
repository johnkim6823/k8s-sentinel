import pytest
from pydantic import ValidationError

from agent.models import AlertmanagerWebhook

SAMPLE_PAYLOAD = {
    "version": "4",
    "groupKey": '{}:{alertname="ContainerOOMKilled"}',
    "status": "firing",
    "receiver": "sentinel-agent",
    "groupLabels": {"alertname": "ContainerOOMKilled"},
    "commonLabels": {"alertname": "ContainerOOMKilled", "severity": "critical"},
    "commonAnnotations": {},
    "externalURL": "http://alertmanager:9093",
    "alerts": [
        {
            "status": "firing",
            "labels": {
                "alertname": "ContainerOOMKilled",
                "namespace": "default",
                "pod": "app-b-abc123-xyz",
                "container": "app-b",
                "scenario": "oomkilled",
                "severity": "critical",
            },
            "annotations": {"summary": "OOMKilled"},
            "startsAt": "2026-07-30T08:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "fingerprint": "deadbeef",
        }
    ],
}


def test_parse_alertmanager_payload():
    payload = AlertmanagerWebhook.model_validate(SAMPLE_PAYLOAD)
    assert payload.status == "firing"
    alert = payload.alerts[0]
    assert alert.name == "ContainerOOMKilled"
    assert alert.namespace == "default"
    assert alert.pod == "app-b-abc123-xyz"


def test_alert_without_pod_label():
    payload_dict = {**SAMPLE_PAYLOAD}
    payload_dict["alerts"] = [
        {**SAMPLE_PAYLOAD["alerts"][0], "labels": {"alertname": "NodeDiskPressure"}}
    ]
    alert = AlertmanagerWebhook.model_validate(payload_dict).alerts[0]
    assert alert.pod is None
    assert alert.namespace == "default"


def test_invalid_payload_rejected():
    with pytest.raises(ValidationError):
        AlertmanagerWebhook.model_validate({"status": "firing"})  # no alerts key
