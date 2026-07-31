"""Slack reporter — posts diagnosis and remediation reports to a webhook.

SLACK_WEBHOOK_URL is read from the environment (CLAUDE.md: 시크릿은 환경변수로만).
When unset, report() is a no-op that returns False, so the pipeline runs fine
without Slack configured.
"""

import os
from typing import Any

import httpx


def enabled() -> bool:
    return bool(os.environ.get("SLACK_WEBHOOK_URL"))


def _post(text: str) -> bool:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return False
    try:
        resp = httpx.post(url, json={"text": text}, timeout=10.0)
        resp.raise_for_status()
        return True
    except Exception:  # noqa: BLE001 — reporting must never break the pipeline
        return False


def _confidence(diagnosis: dict[str, Any]) -> str:
    c = diagnosis.get("confidence")
    return f"{c:.0%}" if isinstance(c, (int, float)) else "n/a"


def report_diagnosis(alert_name: str, diagnosis: dict[str, Any]) -> bool:
    if "error" in diagnosis or "skipped" in diagnosis:
        detail = diagnosis.get("error") or diagnosis.get("skipped")
        return _post(f":warning: *{alert_name}* — diagnosis unavailable ({detail})")
    lines = [
        f":rotating_light: *{alert_name}*",
        f"*Root cause:* {diagnosis.get('root_cause', 'unknown')}",
        f"*Confidence:* {_confidence(diagnosis)}",
        f"*Recommended action:* `{diagnosis.get('recommended_action', 'none')}` "
        f"(safe to automate: {diagnosis.get('action_safe_to_automate', False)})",
    ]
    evidence = diagnosis.get("evidence") or []
    if evidence:
        lines.append("*Evidence:*")
        lines += [f"  • {e}" for e in evidence[:5]]
    return _post("\n".join(lines))


def report_remediation(
    alert_name: str, action: str, status: str, result: dict[str, Any] | None = None
) -> bool:
    emoji = {"verified": ":white_check_mark:", "executed": ":gear:",
             "failed": ":x:", "rejected": ":no_entry:"}.get(status, ":information_source:")
    text = f"{emoji} *{alert_name}* — remediation `{action}` → *{status}*"
    if result:
        text += f"\n```{result}```"
    return _post(text)
