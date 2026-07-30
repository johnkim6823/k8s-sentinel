"""Diagnosis engine: structured prompt → Claude API → validated Diagnosis.

Uses structured outputs (output_config.format) so the response is guaranteed
to match DIAGNOSIS_JSON_SCHEMA, then validates with pydantic for the
constraints JSON schema can't express (confidence bounds, non-empty evidence).
Ships with the server-side refusal fallback enabled: if a safety classifier
declines the request on the primary model, the API retries it on Anthropic's
recommended fallback model in the same call.
"""

import json
import os
from functools import lru_cache
from typing import Any

import anthropic

from agent.diagnosis.prompt import SYSTEM_PROMPT, build_prompt
from agent.diagnosis.schema import DIAGNOSIS_JSON_SCHEMA, Diagnosis

DIAGNOSIS_MODEL = os.environ.get("DIAGNOSIS_MODEL", "claude-opus-5")
MAX_TOKENS = 16000


class DiagnosisError(Exception):
    """The diagnosis could not be produced (API, refusal, or validation)."""


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def diagnose(context: dict[str, Any]) -> Diagnosis:
    try:
        response = _client().beta.messages.create(
            model=DIAGNOSIS_MODEL,
            max_tokens=MAX_TOKENS,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(context)}],
            output_config={
                "format": {"type": "json_schema", "schema": DIAGNOSIS_JSON_SCHEMA}
            },
        )
    except anthropic.APIError as exc:
        raise DiagnosisError(f"Claude API call failed: {exc}") from exc

    if response.stop_reason == "refusal":
        raise DiagnosisError("model declined the request (stop_reason=refusal)")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise DiagnosisError(f"no text block in response (stop_reason={response.stop_reason})")

    try:
        return Diagnosis.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise DiagnosisError(f"invalid diagnosis payload: {exc}") from exc
