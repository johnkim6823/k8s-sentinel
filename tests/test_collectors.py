import json
from unittest.mock import patch

import httpx

from agent.collector import k8s, loki, prometheus


def _response(payload: dict, url: str = "http://test") -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("GET", url))


def test_prometheus_collect_parses_results():
    payload = {
        "data": {
            "result": [
                {"metric": {"container": "app-b"}, "value": [1753860000, "2"]}
            ]
        }
    }
    with patch("agent.collector.prometheus.httpx.get", return_value=_response(payload)):
        out = prometheus.collect("default", "app-b-xyz")
    assert out["restarts_total"] == [{"labels": {"container": "app-b"}, "value": "2"}]
    assert set(out) == set(prometheus.POD_QUERIES)


def test_prometheus_collect_records_errors():
    with patch(
        "agent.collector.prometheus.httpx.get",
        side_effect=httpx.ConnectError("refused"),
    ):
        out = prometheus.collect("default", "app-b-xyz")
    assert all("error" in v for v in out.values())


def test_loki_collect_sorts_and_limits_lines():
    payload = {
        "data": {
            "result": [
                {"values": [["3", "third"], ["1", "first"]]},
                {"values": [["2", "second"]]},
            ]
        }
    }
    with patch("agent.collector.loki.httpx.get", return_value=_response(payload)):
        out = loki.collect("default", "app-b-xyz")
    assert [line["line"] for line in out["lines"]] == ["first", "second", "third"]


def test_loki_collect_records_error():
    with patch(
        "agent.collector.loki.httpx.get", side_effect=httpx.ConnectError("refused")
    ):
        out = loki.collect("default", "app-b-xyz")
    assert "error" in out


def _k8s_get(responses: dict[str, dict]):
    def fake_get(path: str, params=None):
        for prefix, payload in responses.items():
            if path.startswith(prefix):
                return payload
        raise AssertionError(f"unexpected path {path}")

    return fake_get


def test_k8s_collect_gathers_status_events_history():
    deploy_uid = "uid-1"
    responses = {
        "/api/v1/namespaces/default/pods/app-b-abc123-xyz": {
            "status": {
                "phase": "Running",
                "containerStatuses": [{"name": "app-b", "restartCount": 1}],
            },
            "spec": {"nodeName": "worker"},
        },
        "/api/v1/namespaces/default/events": {
            "items": [
                {"type": "Warning", "reason": "BackOff", "message": "x",
                 "count": 3, "lastTimestamp": "t"}
            ]
        },
        "/apis/apps/v1/namespaces/default/deployments/app-b": {
            "metadata": {"uid": deploy_uid}
        },
        "/apis/apps/v1/namespaces/default/replicasets": {
            "items": [
                {
                    "metadata": {
                        "ownerReferences": [{"uid": deploy_uid}],
                        "annotations": {"deployment.kubernetes.io/revision": "2"},
                    },
                    "spec": {"template": {"spec": {"containers": [
                        {"name": "app-b", "image": "app-b:dev"}
                    ]}}},
                    "status": {"replicas": 1},
                },
                {
                    "metadata": {"ownerReferences": [{"uid": "other"}]},
                    "spec": {"template": {"spec": {"containers": []}}},
                    "status": {},
                },
            ]
        },
    }
    with patch("agent.collector.k8s._get", side_effect=_k8s_get(responses)):
        out = k8s.collect("default", "app-b-abc123-xyz")
    assert out["pod_status"]["phase"] == "Running"
    assert out["events"][0]["reason"] == "BackOff"
    assert out["rollout_history"] == [
        {"revision": 2, "images": ["app-b:dev"], "env": {}, "replicas": 1}
    ]


def test_k8s_collect_without_pod():
    assert "error" in k8s.collect("default", None)


def test_context_is_json_serializable():
    from agent.collector import collect_context
    from agent.models import Alert

    alert = Alert(
        status="firing",
        labels={"alertname": "X", "namespace": "default", "pod": "app-b-abc123-xyz"},
        startsAt="2026-07-30T08:00:00Z",
    )
    with (
        patch("agent.collector.k8s.collect", return_value={"ok": True}),
        patch("agent.collector.prometheus.collect", return_value={"ok": True}),
        patch("agent.collector.loki.collect", return_value={"ok": True}),
    ):
        context = collect_context(alert)
    json.dumps(context)
    assert context["kubernetes"] == {"ok": True}
