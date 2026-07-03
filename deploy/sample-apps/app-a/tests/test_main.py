from unittest.mock import patch

import httpx
from app.main import DOWNSTREAM_CALLS, app
from fastapi.testclient import TestClient

client = TestClient(app)


def _counter_value(outcome: str) -> float:
    return DOWNSTREAM_CALLS.labels(downstream="app-b", outcome=outcome)._value.get()


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_call_b_success():
    before = _counter_value("success")
    fake_response = httpx.Response(
        200, json={"id": "1", "name": "widget"}, request=httpx.Request("GET", "http://app-b/data/1")
    )
    with patch("app.main.httpx.get", return_value=fake_response):
        resp = client.get("/call-b/1")
    assert resp.status_code == 200
    assert resp.json() == {"from": "app-a", "app_b_data": {"id": "1", "name": "widget"}}
    assert _counter_value("success") == before + 1


def test_call_b_not_found():
    fake_response = httpx.Response(
        404, request=httpx.Request("GET", "http://app-b/data/999")
    )
    with patch("app.main.httpx.get", return_value=fake_response):
        resp = client.get("/call-b/999")
    assert resp.status_code == 404


def test_call_b_unreachable():
    before = _counter_value("error")
    with patch("app.main.httpx.get", side_effect=httpx.ConnectError("connection refused")):
        resp = client.get("/call-b/1")
    assert resp.status_code == 502
    assert _counter_value("error") == before + 1


def test_metrics_endpoint():
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "app_a_downstream_calls_total" in resp.text


def test_debug_memory_hold_and_release():
    resp = client.get("/debug/memory", params={"mb": 5})
    assert resp.json() == {"held_mb": 5}

    resp = client.get("/debug/memory", params={"mb": 0})
    assert resp.json() == {"held_mb": 0}


def test_debug_cpu():
    resp = client.get("/debug/cpu", params={"seconds": 0.1})
    assert resp.status_code == 200
    assert resp.json()["cpu_burn_seconds"] == 0.1
