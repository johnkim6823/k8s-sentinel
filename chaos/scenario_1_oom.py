"""Scenario 1 — OOMKilled.

inject:  lower app-b's memory limit, then allocate memory via /debug/memory
         until the kernel OOM-kills the container.
restore: put the original memory limit back (the rolling update replaces the
         pod, which also drops the held memory).

Expected alert: ContainerOOMKilled (scenario=oomkilled).
"""

import json
import subprocess

import common

SCENARIO = "scenario_1_oom"
DEPLOYMENT = "app-b"
CHAOS_MEMORY_LIMIT = "96Mi"
LOAD_MB = 100


def inject() -> None:
    original_limit = common.deployment_field(
        DEPLOYMENT, "{.spec.template.spec.containers[0].resources.limits.memory}"
    )
    print(f"original memory limit: {original_limit}, lowering to {CHAOS_MEMORY_LIMIT}")
    common.kubectl(
        "set", "resources", f"deployment/{DEPLOYMENT}",
        f"--limits=memory={CHAOS_MEMORY_LIMIT}",
    )
    common.wait_rollout(DEPLOYMENT)

    # injected_at marks the moment the OOM trigger fires (not the limit patch),
    # so alert-latency measurements start from the actual fault
    log_path = common.write_injection_log(
        SCENARIO,
        target={"namespace": common.NAMESPACE, "deployment": DEPLOYMENT},
        parameters={
            "original_memory_limit": original_limit,
            "chaos_memory_limit": CHAOS_MEMORY_LIMIT,
            "load_mb": LOAD_MB,
        },
    )

    print(f"allocating {LOAD_MB}MB inside app-b (the connection dying is expected)")
    script = (
        "import urllib.request; "
        f"print(urllib.request.urlopen('http://app-b:8000/debug/memory?mb={LOAD_MB}',"
        " timeout=30).read().decode())"
    )
    result = subprocess.run(
        ["kubectl", "-n", common.NAMESPACE, "exec", "deploy/app-a", "--",
         "python3", "-c", script],
        capture_output=True, text=True, check=False,
    )
    if result.returncode == 0:
        print(f"warning: allocation survived ({result.stdout.strip()}) — "
              "check whether the memory limit is actually enforced")
    else:
        print("app-b connection dropped — OOM kill in progress")
    print(f"injected. log: {log_path}")


def restore() -> None:
    log_path = common.latest_open_log(SCENARIO)
    original_limit = json.loads(log_path.read_text())["parameters"]["original_memory_limit"]
    print(f"restoring memory limit to {original_limit}")
    common.kubectl(
        "set", "resources", f"deployment/{DEPLOYMENT}",
        f"--limits=memory={original_limit}",
    )
    common.wait_rollout(DEPLOYMENT)
    if not common.check_service_health():
        raise SystemExit("app-b health check failed after restore")
    print("app-b healthy")
    common.mark_restored(log_path)


if __name__ == "__main__":
    common.scenario_cli(__doc__, inject, restore)
