"""Payloads exported outside the workflow's local persistence boundary."""

from __future__ import annotations

import re
from typing import Any

from harbor_agent.runtime.sanitizer import sanitize_runtime_payload, sanitize_text

_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)")
_METADATA_KEYS = frozenset(
    {
        "workflow_id",
        "execution_id",
        "trace_id",
        "event_id",
        "event_type",
        "agent_name",
        "turn",
        "attempt",
        "tool_name",
        "tool_call_id",
        "arguments_sha256",
        "goal",
        "status",
        "decision",
        "next_agent",
        "allowed_decision",
        "allowed_tools",
        "proposed_tools",
        "selected_tools",
        "policy_result",
        "reason_code",
        "mode",
        "received_response",
        "outcome",
        "error_type",
        "http_status",
        "source_mode",
        "action",
        "review_kind",
        "approval_id",
        "conflict_count",
        "tool_calls",
        "message_count",
        "cost_basis",
        "case_id",
        "data_source",
        "schema_version",
        "input_fields",
        "output_fields",
        "tool_executed",
        "synthetic_content",
        "prompt_version",
        "provider",
        "sequence",
    }
)


def safe_text(value: object) -> str | None:
    text = sanitize_text(value)
    if text is None:
        return None
    return _PHONE.sub("[phone]", _EMAIL.sub("[email]", text))


def safe_content(value: Any) -> Any:
    """Clean explicitly enabled synthetic evaluation content before recording."""
    value = sanitize_runtime_payload(value)
    if isinstance(value, dict):
        return {key: safe_content(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_content(item) for item in value]
    return safe_text(value) if isinstance(value, str) else value


def safe_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    return {
        key: safe_content(item)
        for key, item in (value or {}).items()
        if key in _METADATA_KEYS and item is not None
    }
