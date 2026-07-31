from unittest.mock import patch

from agent.reporter import slack


def test_enabled_follows_env(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert slack.enabled() is False
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    assert slack.enabled() is True


def test_report_noop_without_webhook(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert slack.report_diagnosis("X", {"root_cause": "y", "evidence": [],
                                        "confidence": 0.5}) is False


def test_report_diagnosis_posts_formatted_message(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    diag = {
        "root_cause": "bad image", "evidence": ["Failed to pull"],
        "confidence": 0.9, "recommended_action": "rollback_deployment",
        "action_safe_to_automate": True,
    }
    with patch("agent.reporter.slack.httpx.post") as p:
        p.return_value.raise_for_status = lambda: None
        assert slack.report_diagnosis("ImagePull", diag) is True
    text = p.call_args.kwargs["json"]["text"]
    assert "ImagePull" in text and "rollback_deployment" in text
    assert "90%" in text and "Failed to pull" in text


def test_report_diagnosis_handles_skip(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    with patch("agent.reporter.slack.httpx.post") as p:
        p.return_value.raise_for_status = lambda: None
        slack.report_diagnosis("X", {"skipped": "no key"})
    assert "diagnosis unavailable" in p.call_args.kwargs["json"]["text"]


def test_report_never_raises_on_http_error(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    with patch("agent.reporter.slack.httpx.post", side_effect=Exception("boom")):
        assert slack.report_remediation("X", "restart_pod", "verified") is False
