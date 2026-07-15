"""Scenario 2 — CrashLoopBackOff.

inject:  roll out an app-b revision with an invalid DATA_BACKEND env var;
         the app validates it at startup and exits immediately, so the new
         pod crash-loops (the old pod keeps serving: maxUnavailable=0).
restore: remove the bad env var, returning to the pre-injection revision.

Expected alert: ContainerCrashLoopBackOff (scenario=crashloop).
"""

import json
import time

import common

SCENARIO = "scenario_2_crashloop"
DEPLOYMENT = "app-b"
ENV_NAME = "DATA_BACKEND"
BAD_VALUE = "postgres"


def inject() -> None:
    original_value = common.deployment_field(
        DEPLOYMENT,
        f'{{.spec.template.spec.containers[0].env[?(@.name=="{ENV_NAME}")].value}}',
    )
    log_path = common.write_injection_log(
        SCENARIO,
        target={"namespace": common.NAMESPACE, "deployment": DEPLOYMENT},
        parameters={
            "env_name": ENV_NAME,
            "bad_value": BAD_VALUE,
            "original_value": original_value or None,
        },
    )
    common.kubectl("set", "env", f"deployment/{DEPLOYMENT}", f"{ENV_NAME}={BAD_VALUE}")

    print("waiting for the new pod to start crashing (up to 90s)")
    for _ in range(30):
        reasons = common.kubectl(
            "get", "pods", "-l", f"app={DEPLOYMENT}",
            "-o", "jsonpath={range .items[*]}"
                  "{.status.containerStatuses[0].state.waiting.reason}{\"\\n\"}{end}",
        )
        if "CrashLoopBackOff" in reasons or "Error" in reasons:
            print(f"new pod is crashing (reasons seen: {reasons.split()})")
            break
        time.sleep(3)
    print(f"injected. log: {log_path}")


def restore() -> None:
    log_path = common.latest_open_log(SCENARIO)
    original_value = json.loads(log_path.read_text())["parameters"]["original_value"]
    if original_value:
        common.kubectl(
            "set", "env", f"deployment/{DEPLOYMENT}", f"{ENV_NAME}={original_value}"
        )
    else:
        common.kubectl("set", "env", f"deployment/{DEPLOYMENT}", f"{ENV_NAME}-")
    common.wait_rollout(DEPLOYMENT)
    if not common.check_service_health():
        raise SystemExit("app-b health check failed after restore")
    print("app-b healthy")
    common.mark_restored(log_path)


if __name__ == "__main__":
    common.scenario_cli(__doc__, inject, restore)
