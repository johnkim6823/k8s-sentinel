"""Collect recent pod logs from the Loki HTTP API."""

import os
import time
from typing import Any

import httpx

LOKI_URL = os.environ.get("LOKI_URL", "http://loki.monitoring:3100")


def collect(
    namespace: str, pod: str, minutes: int = 10, limit: int = 100
) -> dict[str, Any]:
    """Fetch the last `limit` log lines for a pod (matches restarted pods too)."""
    logql = f'{{namespace="{namespace}", pod=~"{pod}.*"}}'
    end_ns = int(time.time() * 1e9)
    start_ns = end_ns - minutes * 60 * 1_000_000_000
    try:
        resp = httpx.get(
            f"{LOKI_URL}/loki/api/v1/query_range",
            params={
                "query": logql,
                "start": start_ns,
                "end": end_ns,
                "limit": limit,
                "direction": "backward",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        streams = resp.json()["data"]["result"]
    except Exception as exc:  # noqa: BLE001 — context collection must not fail
        return {"error": str(exc)}

    lines = [
        {"ts": value[0], "line": value[1]}
        for stream in streams
        for value in stream["values"]
    ]
    lines.sort(key=lambda entry: entry["ts"])
    return {"query": logql, "lines": lines[-limit:]}
