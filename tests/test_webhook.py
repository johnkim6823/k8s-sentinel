from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.main import CONTEXTS, app
from tests.test_models import SAMPLE_PAYLOAD

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_webhook_collects_context_for_firing_alerts(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    CONTEXTS.clear()
    with patch("agent.main.collect_context", return_value={"fake": "context"}):
        resp = client.post("/webhook", json=SAMPLE_PAYLOAD)
    assert resp.status_code == 200
    assert resp.json() == {"accepted": 1, "ignored_resolved": 0}
    # TestClient runs background tasks before returning; without an API key
    # the diagnosis step is skipped but recorded
    assert list(CONTEXTS) == [
        {"fake": "context", "diagnosis": {"skipped": "ANTHROPIC_API_KEY not configured"}}
    ]
    assert client.get("/contexts").json() == list(CONTEXTS)


def test_webhook_attaches_diagnosis_when_enabled(monkeypatch):
    from agent.diagnosis.schema import Diagnosis

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    CONTEXTS.clear()
    fake = Diagnosis(
        root_cause="bad image tag rolled out",
        evidence=["event: Failed to pull image"],
        confidence=0.9,
        recommended_action="rollback_deployment",
        action_safe_to_automate=True,
    )
    with (
        patch("agent.main.collect_context", return_value={"fake": "context"}),
        patch("agent.diagnosis.diagnose", return_value=fake),
    ):
        client.post("/webhook", json=SAMPLE_PAYLOAD)
    assert CONTEXTS[0]["diagnosis"]["recommended_action"] == "rollback_deployment"


def test_webhook_survives_diagnosis_failure(monkeypatch):
    from agent.diagnosis import DiagnosisError

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    CONTEXTS.clear()
    with (
        patch("agent.main.collect_context", return_value={"fake": "context"}),
        patch("agent.diagnosis.diagnose", side_effect=DiagnosisError("api down")),
    ):
        resp = client.post("/webhook", json=SAMPLE_PAYLOAD)
    assert resp.status_code == 200
    assert CONTEXTS[0]["diagnosis"] == {"error": "api down"}


def test_webhook_ignores_resolved_alerts():
    CONTEXTS.clear()
    payload = {**SAMPLE_PAYLOAD}
    payload["alerts"] = [{**SAMPLE_PAYLOAD["alerts"][0], "status": "resolved"}]
    with patch("agent.main.collect_context", return_value={"fake": "context"}):
        resp = client.post("/webhook", json=payload)
    assert resp.json() == {"accepted": 0, "ignored_resolved": 1}
    assert not CONTEXTS


def test_webhook_rejects_malformed_payload():
    resp = client.post("/webhook", json={"nope": True})
    assert resp.status_code == 422
