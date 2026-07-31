from agent.storage import history


def _db(tmp_path):
    return tmp_path / "test.db"


def test_record_and_get(tmp_path):
    db = _db(tmp_path)
    rid = history.record_request(
        "ContainerOOMKilled", "default", "app-b", "restart_pod",
        {"replicas": 2}, dry_run={"operation": "restart"}, db_path=db,
    )
    rec = history.get(rid, db_path=db)
    assert rec["status"] == "requested"
    assert rec["action"] == "restart_pod"
    assert rec["params"] == {"replicas": 2}
    assert rec["dry_run"] == {"operation": "restart"}
    assert rec["requested_at"] and rec["executed_at"] is None


def test_status_transitions_stamp_timestamps(tmp_path):
    db = _db(tmp_path)
    rid = history.record_request("A", "default", "app-b", "scale_deployment", {}, db_path=db)
    history.update_status(rid, "approved", db_path=db)
    assert history.get(rid, db_path=db)["status"] == "approved"

    history.update_status(rid, "executed", result={"scaled": "app-b"},
                          executed=True, db_path=db)
    rec = history.get(rid, db_path=db)
    assert rec["executed_at"] is not None and rec["verified_at"] is None
    assert rec["result"] == {"scaled": "app-b"}

    history.update_status(rid, "verified", verified=True, db_path=db)
    assert history.get(rid, db_path=db)["verified_at"] is not None


def test_list_recent_newest_first(tmp_path):
    db = _db(tmp_path)
    ids = [
        history.record_request(f"a{i}", "default", "app-b", "restart_pod", {}, db_path=db)
        for i in range(3)
    ]
    recent = history.list_recent(db_path=db)
    assert [r["id"] for r in recent] == list(reversed(ids))


def test_get_missing_returns_none(tmp_path):
    assert history.get(999, db_path=_db(tmp_path)) is None
