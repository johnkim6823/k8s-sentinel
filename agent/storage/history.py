"""SQLite execution history for remediation actions (CLAUDE.md 안전 규칙:
모든 실행은 storage에 이력 기록 — 알람, 조치, 결과, 시각).

One row per remediation attempt, updated in place as it moves through
requested -> dry_run -> approved/rejected -> executed -> verified/failed.
"""

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _default_db() -> Path:
    return Path(os.environ.get("SENTINEL_DB", "/data/sentinel.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS remediations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_name TEXT NOT NULL,
    namespace TEXT NOT NULL,
    target TEXT NOT NULL,
    action TEXT NOT NULL,
    params TEXT NOT NULL,
    status TEXT NOT NULL,
    dry_run TEXT,
    result TEXT,
    requested_at TEXT NOT NULL,
    executed_at TEXT,
    verified_at TEXT
);
"""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _connect(path: Path | str | None = None) -> sqlite3.Connection:
    db = Path(path) if path else _default_db()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def record_request(
    alert_name: str,
    namespace: str,
    target: str,
    action: str,
    params: dict[str, Any],
    dry_run: dict[str, Any] | None = None,
    db_path: Path | str | None = None,
) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO remediations
               (alert_name, namespace, target, action, params, status, dry_run, requested_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                alert_name, namespace, target, action,
                json.dumps(params), "requested",
                json.dumps(dry_run) if dry_run is not None else None,
                _utc_now(),
            ),
        )
        return cur.lastrowid


def update_status(
    remediation_id: int,
    status: str,
    result: dict[str, Any] | None = None,
    executed: bool = False,
    verified: bool = False,
    db_path: Path | str | None = None,
) -> None:
    fields = ["status = ?"]
    values: list[Any] = [status]
    if result is not None:
        fields.append("result = ?")
        values.append(json.dumps(result))
    if executed:
        fields.append("executed_at = ?")
        values.append(_utc_now())
    if verified:
        fields.append("verified_at = ?")
        values.append(_utc_now())
    values.append(remediation_id)
    with _connect(db_path) as conn:
        conn.execute(
            f"UPDATE remediations SET {', '.join(fields)} WHERE id = ?", values
        )


def get(remediation_id: int, db_path: Path | str | None = None) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM remediations WHERE id = ?", (remediation_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_recent(limit: int = 20, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM remediations ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("params", "dry_run", "result"):
        if d.get(key):
            d[key] = json.loads(d[key])
    return d
