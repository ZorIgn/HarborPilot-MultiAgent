from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class TraceEventType(str, Enum):
    WORKFLOW_START = "WORKFLOW_START"
    WORKFLOW_END = "WORKFLOW_END"
    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"
    SUPERVISOR_ROUTE = "SUPERVISOR_ROUTE"
    AGENT_STARTED = "AGENT_STARTED"
    AGENT_START = "AGENT_START"
    AGENT_END = "AGENT_END"
    AGENT_ENDED = "AGENT_ENDED"
    AGENT_DECISION = "AGENT_DECISION"
    LLM_REQUEST = "LLM_REQUEST"
    LLM_RESPONSE = "LLM_RESPONSE"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    HANDOFF = "HANDOFF"
    CHECKPOINT = "CHECKPOINT"
    USER_WAIT = "USER_WAIT"
    HUMAN_WAIT = "HUMAN_WAIT"
    RETRY = "RETRY"
    ERROR = "ERROR"


class RuntimeTraceEvent(BaseModel):
    """A trace event emitted only by an actual runtime action."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    workflow_id: str
    parent_event_id: str | None = None
    event_type: TraceEventType
    agent_name: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    model: str | None = None
    provider: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    error_type: str | None = None
    error_message: str | None = None
