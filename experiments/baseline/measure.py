"""Record a manual-recovery MTTR measurement for the baseline experiment.

Usage:
    python experiments/baseline/measure.py done --scenario {1,2,3} \
        [--notes "..."] [--rehearsal]

Reads the newest chaos injection log for the scenario (injected_at = MTTR
start), then verifies recovery automatically — the scenario's alert must be
absent from Prometheus (resolved) and the target Deployment fully Ready —
polling until both hold. The moment verification passes is
recovery_confirmed_at; human judgement is deliberately not part of the
measurement. Appends one JSON line to results.jsonl (or
rehearsal-results.jsonl with --rehearsal):

    {scenario, run, injected_at, recovery_confirmed_at, mttr_seconds, notes}

Requires a Prometheus port-forward (default http://localhost:9090, override
with PROMETHEUS_URL).
"""

import argparse
import json
import os
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

BASELINE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASELINE_DIR.parent / "logs"
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
POLL_INTERVAL_S = 5
VERIFY_TIMEOUT_S = 600

SCENARIOS: dict[int, dict] = {
    1: {"log_prefix": "scenario_1_oom", "alertname": "ContainerOOMKilled"},
    2: {"log_prefix": "scenario_2_crashloop", "alertname": "ContainerCrashLoopBackOff"},
    3: {"log_prefix": "scenario_3_imagepull", "alertname": "ContainerImagePullBackOff"},
}


def latest_injection_log(log_prefix: str) -> dict:
    candidates = sorted(LOG_DIR.glob(f"{log_prefix}_*.json"), reverse=True)
    if not candidates:
        raise SystemExit(f"no injection log found for {log_prefix} in {LOG_DIR}")
    return json.loads(candidates[0].read_text())


def alert_resolved(alertname: str) -> bool:
    with urllib.request.urlopen(f"{PROMETHEUS_URL}/api/v1/alerts", timeout=10) as resp:
        alerts = json.load(resp)["data"]["alerts"]
    return not any(a["labels"].get("alertname") == alertname for a in alerts)


def deployment_ready(namespace: str, deployment: str) -> bool:
    out = subprocess.run(
        ["kubectl", "-n", namespace, "get", "deployment", deployment, "-o", "json"],
        capture_output=True, text=True, check=True,
    ).stdout
    status = json.loads(out)["status"]
    desired = json.loads(out)["spec"].get("replicas", 1)
    return (
        status.get("readyReplicas", 0) == desired
        and status.get("updatedReplicas", 0) == desired
        and status.get("unavailableReplicas", 0) == 0
    )


def verify_recovery(alertname: str, namespace: str, deployment: str) -> str:
    """Poll until the alert is resolved and the deployment is Ready."""
    deadline = time.monotonic() + VERIFY_TIMEOUT_S
    while time.monotonic() < deadline:
        resolved = alert_resolved(alertname)
        ready = deployment_ready(namespace, deployment)
        if resolved and ready:
            return datetime.now(UTC).isoformat(timespec="seconds")
        state = f"alert_resolved={resolved} deployment_ready={ready}"
        print(f"waiting for recovery... ({state})")
        time.sleep(POLL_INTERVAL_S)
    raise SystemExit(f"recovery not confirmed within {VERIFY_TIMEOUT_S}s")


def next_run_number(results_path: Path, scenario: int) -> int:
    if not results_path.exists():
        return 1
    runs = [
        json.loads(line)["run"]
        for line in results_path.read_text().splitlines()
        if line.strip() and json.loads(line)["scenario"] == scenario
    ]
    return max(runs, default=0) + 1


def cmd_done(scenario: int, notes: str, rehearsal: bool) -> None:
    spec = SCENARIOS[scenario]
    injection = latest_injection_log(spec["log_prefix"])
    target = injection["target"]

    recovery_confirmed_at = verify_recovery(
        spec["alertname"], target["namespace"], target["deployment"]
    )
    injected_at = injection["injected_at"]
    mttr_seconds = int(
        (datetime.fromisoformat(recovery_confirmed_at)
         - datetime.fromisoformat(injected_at)).total_seconds()
    )

    results_path = BASELINE_DIR / (
        "rehearsal-results.jsonl" if rehearsal else "results.jsonl"
    )
    record = {
        "scenario": scenario,
        "run": next_run_number(results_path, scenario),
        "injected_at": injected_at,
        "recovery_confirmed_at": recovery_confirmed_at,
        "mttr_seconds": mttr_seconds,
        "notes": notes,
    }
    with results_path.open("a") as f:
        f.write(json.dumps(record) + "\n")
    print(json.dumps(record, indent=2))
    print(f"appended to {results_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    done = sub.add_parser("done", help="record that manual recovery is complete")
    done.add_argument("--scenario", type=int, choices=sorted(SCENARIOS), required=True)
    done.add_argument("--notes", default="")
    done.add_argument(
        "--rehearsal", action="store_true",
        help="write to rehearsal-results.jsonl instead of results.jsonl",
    )
    args = parser.parse_args()
    cmd_done(args.scenario, args.notes, args.rehearsal)


if __name__ == "__main__":
    main()
