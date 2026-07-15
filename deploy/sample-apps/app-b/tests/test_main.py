import pytest
from app.main import app, validate_config
from fastapi.testclient import TestClient

client = TestClient(app)


def test_validate_config_default_ok(monkeypatch):
    monkeypatch.delenv("DATA_BACKEND", raising=False)
    assert validate_config() == "memory"


def test_validate_config_valid_value(monkeypatch):
    monkeypatch.setenv("DATA_BACKEND", "memory")
    assert validate_config() == "memory"


def test_validate_config_invalid_value_exits(monkeypatch):
    monkeypatch.setenv("DATA_BACKEND", "postgres")
    with pytest.raises(SystemExit) as exc:
        validate_config()
    assert exc.value.code == 1


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_get_data_found():
    resp = client.get("/data/1")
    assert resp.status_code == 200
    assert resp.json() == {"id": "1", "name": "widget"}


def test_get_data_not_found():
    resp = client.get("/data/does-not-exist")
    assert resp.status_code == 404


def test_debug_memory_hold_and_release():
    resp = client.get("/debug/memory", params={"mb": 10})
    assert resp.json() == {"held_mb": 10}

    resp = client.get("/debug/memory", params={"mb": 0})
    assert resp.json() == {"held_mb": 0}


def test_debug_cpu():
    resp = client.get("/debug/cpu", params={"seconds": 0.1})
    assert resp.status_code == 200
    assert resp.json()["cpu_burn_seconds"] == 0.1
