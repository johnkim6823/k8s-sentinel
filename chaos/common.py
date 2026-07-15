"""Shared helpers for chaos injection scripts.

Every scenario script exposes two subcommands:

    python chaos/scenario_N_*.py inject
    python chaos/scenario_N_*.py restore

`inject` writes a JSON record to experiments/logs/ (the MTTR measurement
start point); `restore` reverts the fault and stamps restored_at into the
same record.
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = REPO_ROOT / "experiments" / "logs"

NAMESPACE = "default"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def run(*cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command, echoing it, capturing output."""
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def kubectl(*args: str, check: bool = True) -> str:
    result = run("kubectl", "-n", NAMESPACE, *args, check=check)
    return result.stdout.strip()


def deployment_field(deployment: str, jsonpath: str) -> str:
    return kubectl("get", "deployment", deployment, "-o", f"jsonpath={jsonpath}")


def wait_rollout(deployment: str, timeout: str = "120s") -> None:
    kubectl("rollout", "status", f"deployment/{deployment}", f"--timeout={timeout}")


def check_service_health(url: str = "http://app-b:8000/health", attempts: int = 5) -> bool:
    """Probe a service URL from inside the cluster (via the app-a pod).

    Retries a few times: right after a rollout the Service endpoints may still
    be switching over.
    """
    script = f"import urllib.request; urllib.request.urlopen('{url}', timeout=5)"
    for attempt in range(attempts):
        result = run(
            "kubectl", "-n", NAMESPACE, "exec", "deploy/app-a", "--",
            "python3", "-c", script, check=False,
        )
        if result.returncode == 0:
            return True
        if attempt < attempts - 1:
            time.sleep(3)
    return False


def write_injection_log(scenario: str, target: dict, parameters: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    injected_at = utc_now()
    stamp = injected_at.replace(":", "").replace("-", "").replace("+0000", "Z")
    path = LOG_DIR / f"{scenario}_{stamp}.json"
    record = {
        "scenario": scenario,
        "injected_at": injected_at,
        "parameters": parameters,
        "target": target,
    }
    path.write_text(json.dumps(record, indent=2) + "\n")
    print(f"injection log: {path}")
    return path


def latest_open_log(scenario: str) -> Path:
    """Newest injection log for `scenario` that has not been restored yet."""
    candidates = sorted(LOG_DIR.glob(f"{scenario}_*.json"), reverse=True)
    for path in candidates:
        record = json.loads(path.read_text())
        if "restored_at" not in record:
            return path
    raise SystemExit(f"no un-restored injection log found for scenario {scenario!r}")


def mark_restored(path: Path) -> None:
    record = json.loads(path.read_text())
    record["restored_at"] = utc_now()
    path.write_text(json.dumps(record, indent=2) + "\n")
    print(f"restored_at stamped in {path}")


def scenario_cli(description: str, inject_fn, restore_fn) -> None:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("action", choices=["inject", "restore"])
    action = parser.parse_args().action
    try:
        inject_fn() if action == "inject" else restore_fn()
    except subprocess.CalledProcessError as exc:
        print(f"command failed: {exc.cmd}\nstderr: {exc.stderr}", file=sys.stderr)
        raise SystemExit(1) from exc
