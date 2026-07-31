from unittest.mock import patch

import pytest

from agent.remediation import executor


def test_plan_rejects_non_whitelisted_action():
    with pytest.raises(executor.RemediationError, match="whitelist"):
        executor.plan("delete_namespace", "default", "app-b-x-y")


@pytest.mark.parametrize("scenario", ["node-disk-pressure", "downstream-failure"])
def test_plan_blocks_non_automatable_scenarios(scenario):
    with pytest.raises(executor.NotAutomatable):
        executor.plan("restart_pod", "default", "app-b-x-y", scenario)


def test_plan_restart_maps_pod_to_deployment():
    dry = executor.plan("restart_pod", "default", "app-b-6f9-lppft")
    assert dry["target"] == "app-b"
    assert "rollout restart deployment/app-b" in dry["operation"]


def test_plan_scale_defaults_and_override():
    assert executor.plan("scale_deployment", "default", "app-b")["params"]["replicas"] == 2
    dry = executor.plan("scale_deployment", "default", "app-b", params={"replicas": 4})
    assert dry["params"]["replicas"] == 4


def test_plan_rollback():
    dry = executor.plan("rollback_deployment", "default", "app-b")
    assert dry["action"] == "rollback_deployment"
    assert "previous revision" in dry["operation"]


def test_execute_restart_patches_deployment():
    dry = executor.plan("restart_pod", "default", "app-b-6f9-lppft")
    with patch("agent.remediation.executor.k8s_client.patch") as p:
        result = executor.execute(dry)
    p.assert_called_once()
    path, body, ctype = p.call_args.args
    assert path.endswith("/deployments/app-b")
    assert "sentinel.k8s/restartedAt" in body["spec"]["template"]["metadata"]["annotations"]
    assert result["restarted"] == "app-b"


def test_execute_scale_patches_scale_subresource():
    dry = executor.plan("scale_deployment", "default", "app-b", params={"replicas": 3})
    with patch("agent.remediation.executor.k8s_client.patch") as p:
        result = executor.execute(dry)
    path, body, _ = p.call_args.args
    assert path.endswith("/deployments/app-b/scale")
    assert body["spec"]["replicas"] == 3
    assert result["replicas"] == 3


def test_execute_rollback_targets_prior_revision():
    deploy = {"metadata": {"uid": "u1", "annotations": {
        "deployment.kubernetes.io/revision": "3"}}, "spec": {}}
    replicasets = {"items": [
        {"metadata": {"uid": "rs3", "ownerReferences": [{"uid": "u1"}],
                      "annotations": {"deployment.kubernetes.io/revision": "3"}},
         "spec": {"template": {"spec": {"containers": [{"image": "app-b:bad"}]}}}},
        {"metadata": {"uid": "rs2", "ownerReferences": [{"uid": "u1"}],
                      "annotations": {"deployment.kubernetes.io/revision": "2"}},
         "spec": {"template": {"spec": {"containers": [{"image": "app-b:good"}]}}}},
    ]}

    def fake_get(path, params=None):
        return deploy if path.endswith("/deployments/app-b") else replicasets

    with (
        patch("agent.remediation.executor.k8s_client.get", side_effect=fake_get),
        patch("agent.remediation.executor.k8s_client.patch") as p,
    ):
        result = executor.execute(
            {"action": "rollback_deployment", "namespace": "default", "target": "app-b"}
        )
    _, body, _ = p.call_args.args
    assert body["spec"]["template"]["spec"]["containers"][0]["image"] == "app-b:good"
    assert result == {"rolled_back": "app-b", "from_revision": 3, "to_revision": 2}


def test_rollback_without_prior_revision_errors():
    deploy = {"metadata": {"uid": "u1", "annotations": {
        "deployment.kubernetes.io/revision": "1"}}, "spec": {}}
    replicasets = {"items": [
        {"metadata": {"uid": "rs1", "ownerReferences": [{"uid": "u1"}],
                      "annotations": {"deployment.kubernetes.io/revision": "1"}},
         "spec": {"template": {"spec": {"containers": []}}}},
    ]}

    def fake_get(path, params=None):
        return deploy if path.endswith("/deployments/app-b") else replicasets

    with patch("agent.remediation.executor.k8s_client.get", side_effect=fake_get):
        with pytest.raises(executor.RemediationError, match="no prior revision"):
            executor.execute(
                {"action": "rollback_deployment", "namespace": "default", "target": "app-b"}
            )


def test_verify_alert_cleared_true_when_absent():
    import httpx

    resp = httpx.Response(200, json={"data": {"alerts": []}},
                          request=httpx.Request("GET", "http://p"))
    with patch("agent.remediation.executor.httpx.get", return_value=resp):
        assert executor.verify_alert_cleared("X", timeout_s=1) is True


def test_verify_alert_cleared_false_when_still_firing():
    import httpx

    resp = httpx.Response(200, json={"data": {"alerts": [
        {"labels": {"alertname": "X"}}]}}, request=httpx.Request("GET", "http://p"))
    with (
        patch("agent.remediation.executor.httpx.get", return_value=resp),
        patch("agent.remediation.executor.time.sleep"),
        patch("agent.remediation.executor.time.monotonic", side_effect=[0, 0, 1, 2]),
    ):
        assert executor.verify_alert_cleared("X", timeout_s=1) is False
