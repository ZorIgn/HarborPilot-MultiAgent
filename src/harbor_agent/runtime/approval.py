from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolApprovalRecord(BaseModel):
    """Auditable, one-shot authority for one exact high-risk tool call."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=128)
    agent_name: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=128)
    tool_call_id: str = Field(min_length=1, max_length=256)
    arguments: dict[str, Any]
    arguments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["PENDING", "APPROVED", "REJECTED", "CONSUMED"]
    requested_at: datetime
    expires_at: datetime
    reviewer_id: str | None = None
    reviewer_note: str | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    consumed_at: datetime | None = None


def canonical_tool_arguments(arguments: dict[str, Any]) -> tuple[str, str]:
    """Return stable JSON and SHA-256 after a tool input model has validated it."""

    encoded = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()
