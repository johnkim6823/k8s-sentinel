import pytest


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    """Point the remediation history DB at a per-test temp file so tests never
    touch the real /data/sentinel.db."""
    monkeypatch.setenv("SENTINEL_DB", str(tmp_path / "sentinel.db"))
