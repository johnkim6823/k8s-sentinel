from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.main import CONTEXTS, app
from tests.test_models import SAMPLE_PAYLOAD

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_webhook_collects_context_for_firing_alerts():
    CONTEXTS.clear()
    with patch("agent.main.collect_context", return_value={"fake": "context"}):
        resp = client.post("/webhook", json=SAMPLE_PAYLOAD)
    assert resp.status_code == 200
    assert resp.json() == {"accepted": 1, "ignored_resolved": 0}
    # TestClient runs background tasks before returning
    assert list(CONTEXTS) == [{"fake": "context"}]
    assert client.get("/contexts").json() == [{"fake": "context"}]


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
