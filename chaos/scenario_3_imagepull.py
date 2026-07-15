"""Scenario 3 — ImagePullBackOff.

inject:  roll out an app-b revision pointing at a nonexistent image tag;
         the new pod cannot start (the old pod keeps serving:
         maxUnavailable=0).
restore: set the original image back.

Expected alert: ContainerImagePullBackOff (scenario=imagepull).
"""

import json
import time

import common

SCENARIO = "scenario_3_imagepull"
DEPLOYMENT = "app-b"
CONTAINER = "app-b"


def inject() -> None:
    original_image = common.deployment_field(
        DEPLOYMENT, "{.spec.template.spec.containers[0].image}"
    )
    bad_image = f"{original_image.split(':')[0]}:nonexistent-chaos"
    log_path = common.write_injection_log(
        SCENARIO,
        target={"namespace": common.NAMESPACE, "deployment": DEPLOYMENT},
        parameters={"original_image": original_image, "bad_image": bad_image},
    )
    common.kubectl("set", "image", f"deployment/{DEPLOYMENT}", f"{CONTAINER}={bad_image}")

    print("waiting for the new pod to hit an image pull error (up to 90s)")
    for _ in range(30):
        reasons = common.kubectl(
            "get", "pods", "-l", f"app={DEPLOYMENT}",
            "-o", "jsonpath={range .items[*]}"
                  "{.status.containerStatuses[0].state.waiting.reason}{\"\\n\"}{end}",
        )
        if "ImagePullBackOff" in reasons or "ErrImagePull" in reasons:
            print(f"new pod cannot pull its image (reasons seen: {reasons.split()})")
            break
        time.sleep(3)
    print(f"injected. log: {log_path}")


def restore() -> None:
    log_path = common.latest_open_log(SCENARIO)
    original_image = json.loads(log_path.read_text())["parameters"]["original_image"]
    common.kubectl(
        "set", "image", f"deployment/{DEPLOYMENT}", f"{CONTAINER}={original_image}"
    )
    common.wait_rollout(DEPLOYMENT)
    if not common.check_service_health():
        raise SystemExit("app-b health check failed after restore")
    print("app-b healthy")
    common.mark_restored(log_path)


if __name__ == "__main__":
    common.scenario_cli(__doc__, inject, restore)
