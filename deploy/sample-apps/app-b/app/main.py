import os
import sys
import time

from fastapi import FastAPI, HTTPException

VALID_DATA_BACKENDS = {"memory"}


def validate_config() -> str:
    """Validate required configuration at startup; exit immediately if invalid.

    Chaos scenario 2 (CrashLoopBackOff) deploys a revision with a bad
    DATA_BACKEND value to simulate a broken config rollout.
    """
    backend = os.environ.get("DATA_BACKEND", "memory")
    if backend not in VALID_DATA_BACKENDS:
        print(
            f"FATAL: invalid DATA_BACKEND {backend!r}; supported: {sorted(VALID_DATA_BACKENDS)}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return backend


DATA_BACKEND = validate_config()

app = FastAPI(title="app-b")

_DATA: dict[str, dict] = {
    "1": {"id": "1", "name": "widget"},
    "2": {"id": "2", "name": "gadget"},
}

_memory_hoard: bytearray | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/data/{item_id}")
def get_data(item_id: str) -> dict:
    item = _DATA.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return item


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
