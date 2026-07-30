"""Diagnosis output schema.

The LLM must return exactly this JSON shape (docs/PLAN.md Week 4):
{root_cause, evidence[], confidence, recommended_action, action_safe_to_automate}

recommended_action is restricted to the remediation whitelist (CLAUDE.md 안전
규칙) plus "none" for alert-only scenarios (5, 6) and anything else the agent
must not touch automatically.
"""

from typing import Literal

from pydantic import BaseModel, Field

RecommendedAction = Literal[
    "restart_pod", "scale_deployment", "rollback_deployment", "none"
]


class Diagnosis(BaseModel):
    root_cause: str
    evidence: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: RecommendedAction
    action_safe_to_automate: bool


# JSON schema sent to the API's structured-output enforcement. Kept free of
# numeric constraints (unsupported there) — pydantic enforces those client-side.
DIAGNOSIS_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "root_cause": {
            "type": "string",
            "description": "One-paragraph root cause statement of the failure",
        },
        "evidence": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Concrete observations from the context that support the root cause",
        },
        "confidence": {
            "type": "number",
            "description": "Confidence in the diagnosis between 0.0 and 1.0",
        },
        "recommended_action": {
            "type": "string",
            "enum": ["restart_pod", "scale_deployment", "rollback_deployment", "none"],
            "description": (
                "Single whitelisted remediation, or 'none' when no automated "
                "action should run"
            ),
        },
        "action_safe_to_automate": {
            "type": "boolean",
            "description": "Whether the recommended action can run without human approval",
        },
    },
    "required": [
        "root_cause",
        "evidence",
        "confidence",
        "recommended_action",
        "action_safe_to_automate",
    ],
    "additionalProperties": False,
}
