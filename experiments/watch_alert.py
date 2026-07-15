"""Wait for a Prometheus alert to reach (or leave) a state, recording evidence.

Usage:
    python experiments/watch_alert.py <alertname> firing   [timeout_s]
    python experiments/watch_alert.py <alertname> resolved [timeout_s]

Polls the Prometheus /api/v1/alerts endpoint (default http://localhost:9090,
override with PROMETHEUS_URL). On success prints the observation timestamp and
saves the raw alerts payload to experiments/logs/. Exit code 1 on timeout.
"""

import json
import os
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
POLL_INTERVAL_S = 5


def fetch_alerts() -> list[dict]:
    with urllib.request.urlopen(f"{PROMETHEUS_URL}/api/v1/alerts", timeout=10) as resp:
        return json.load(resp)["data"]["alerts"]


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[2] not in ("firing", "resolved"):
        print(__doc__)
        return 2
    alertname, want = sys.argv[1], sys.argv[2]
    timeout_s = int(sys.argv[3]) if len(sys.argv) > 3 else 900

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        alerts = [a for a in fetch_alerts() if a["labels"].get("alertname") == alertname]
        hit = (
            any(a["state"] == "firing" for a in alerts)
            if want == "firing"
            else not alerts
        )
        if hit:
            observed_at = datetime.now(UTC).isoformat(timespec="seconds")
            stamp = observed_at.replace(":", "").replace("-", "").replace("+0000", "Z")
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            out = LOG_DIR / f"alert_{alertname}_{want}_{stamp}.json"
            out.write_text(json.dumps({
                "alertname": alertname,
                "state_observed": want,
                "observed_at": observed_at,
                "alerts_snapshot": alerts,
            }, indent=2) + "\n")
            print(f"{alertname} {want} at {observed_at} (snapshot: {out})")
            return 0
        time.sleep(POLL_INTERVAL_S)
    print(f"timeout: {alertname} did not become {want} within {timeout_s}s")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
