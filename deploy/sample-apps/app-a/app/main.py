import os
import time

import httpx
from fastapi import FastAPI, HTTPException

APP_B_URL = os.environ.get("APP_B_URL", "http://app-b:8000")

app = FastAPI(title="app-a")

_memory_hoard: bytearray | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/call-b/{item_id}")
def call_b(item_id: str) -> dict:
    try:
        resp = httpx.get(f"{APP_B_URL}/data/{item_id}", timeout=5.0)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"app-b unreachable: {exc}") from exc
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="item not found")
    resp.raise_for_status()
    return {"from": "app-a", "app_b_data": resp.json()}


@app.get("/debug/memory")
def debug_memory(mb: int = 0) -> dict:
    """mb=0 releases held memory; mb>0 holds that many MB in a bytearray."""
    global _memory_hoard
    if mb <= 0:
        _memory_hoard = None
        return {"held_mb": 0}
    _memory_hoard = bytearray(mb * 1024 * 1024)
    return {"held_mb": mb}


@app.get("/debug/cpu")
def debug_cpu(seconds: float = 5.0) -> dict:
    """Busy-loop for `seconds` to simulate CPU load."""
    end = time.time() + seconds
    while time.time() < end:
        pass
    return {"cpu_burn_seconds": seconds}
