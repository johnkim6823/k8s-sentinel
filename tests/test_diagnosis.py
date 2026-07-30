import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from agent.diagnosis import engine
from agent.diagnosis.prompt import MAX_EVENTS, MAX_LOG_LINES, SYSTEM_PROMPT, build_prompt
from agent.diagnosis.schema import Diagnosis

SAMPLE_CONTEXT = {
    "alert": {
        "name": "ContainerImagePullBackOff",
        "status": "firing",
        "labels": {"namespace": "default", "pod": "app-b-x-y", "scenario": "imagepull"},
        "annotations": {"summary": "cannot pull image"},
        "startsAt": "2026-07-30T08:00:00+00:00",
    },
    "collected_at": "2026-07-30T08:01:00+00:00",
    "kubernetes": {
        "pod_status": {"phase": "Pending"},
        "events": [{"reason": f"e{i}", "message": f"event {i}"} for i in range(30)],
        "rollout_history": [
            {"revision": r, "images": ["app-b:dev"], "env": {}, "replicas": 1}
            for r in range(20, 0, -1)
        ],
    },
    "prometheus": {"waiting_reason": [{"labels": {"reason": "ImagePullBackOff"}, "value": "1"}]},
    "loki": {"lines": [{"ts": str(i), "line": f"log {i}"} for i in range(100)]},
}

VALID_DIAGNOSIS = {
    "root_cause": "Deployment app-b rolled out a nonexistent image tag",
    "evidence": ["event: Failed to pull image app-b:nonexistent-chaos"],
    "confidence": 0.95,
    "recommended_action": "rollback_deployment",
    "action_safe_to_automate": True,
}


def test_build_prompt_includes_key_evidence_and_truncates():
    prompt = build_prompt(SAMPLE_CONTEXT)
    assert "ContainerImagePullBackOff" in prompt
    assert "ImagePullBackOff" in prompt
    payload = prompt.split("## Kubernetes state\n")[1]
    assert payload.count('"event ') == MAX_EVENTS
    assert '"log 99"' in prompt and '"log 0"' not in prompt
    assert prompt.count('"log ') == MAX_LOG_LINES
    # original context must not be mutated by truncation
    assert len(SAMPLE_CONTEXT["loki"]["lines"]) == 100


def test_system_prompt_encodes_safety_rules():
    for action in ("restart_pod", "scale_deployment", "rollback_deployment", "none"):
        assert action in SYSTEM_PROMPT
    assert "downstream" in SYSTEM_PROMPT


def test_diagnosis_schema_validates():
    d = Diagnosis.model_validate(VALID_DIAGNOSIS)
    assert d.recommended_action == "rollback_deployment"


@pytest.mark.parametrize(
    "override",
    [
        {"recommended_action": "delete_namespace"},  # not whitelisted
        {"confidence": 1.5},                          # out of bounds
        {"evidence": []},                             # empty evidence
    ],
)
def test_diagnosis_schema_rejects_invalid(override):
    with pytest.raises(ValidationError):
        Diagnosis.model_validate({**VALID_DIAGNOSIS, **override})


def _fake_response(text: str | None, stop_reason: str = "end_turn"):
    content = [] if text is None else [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(stop_reason=stop_reason, content=content)


def _engine_with(response):
    fake_client = SimpleNamespace(
        beta=SimpleNamespace(
            messages=SimpleNamespace(create=lambda **kwargs: response)
        )
    )
    return patch.object(engine, "_client", lambda: fake_client)


def test_diagnose_parses_valid_response():
    with _engine_with(_fake_response(json.dumps(VALID_DIAGNOSIS))):
        d = engine.diagnose(SAMPLE_CONTEXT)
    assert d.root_cause.startswith("Deployment app-b")
    assert d.action_safe_to_automate is True


def test_diagnose_raises_on_refusal():
    with _engine_with(_fake_response(None, stop_reason="refusal")):
        with pytest.raises(engine.DiagnosisError, match="refusal"):
            engine.diagnose(SAMPLE_CONTEXT)


def test_diagnose_raises_on_invalid_payload():
    with _engine_with(_fake_response('{"root_cause": "x"}')):
        with pytest.raises(engine.DiagnosisError, match="invalid diagnosis payload"):
            engine.diagnose(SAMPLE_CONTEXT)


def test_enabled_follows_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert engine.enabled() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert engine.enabled() is True
