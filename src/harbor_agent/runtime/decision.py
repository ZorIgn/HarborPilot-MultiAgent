from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DecisionType(str, Enum):
    CALL_TOOL = "CALL_TOOL"
    HANDOFF = "HANDOFF"
    ASK_USER = "ASK_USER"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    FAIL = "FAIL"


class ToolCallRequest(BaseModel):
    """A typed request issued by an agent; executor performs it, not the agent."""

    model_config = ConfigDict(extra="forbid")

    # Keep the provider-generated identifier across the decision boundary so
    # trace events and the matching role=tool message can be correlated.
    call_id: str | None = Field(default=None, min_length=1, max_length=256)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentDecision(BaseModel):
    """The only supported control-plane output from a specialized agent."""

    model_config = ConfigDict(extra="forbid")

    decision: DecisionType
    reasoning_summary: str = Field(min_length=1, max_length=1000)
    next_agent: str | None = None
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    state_patch: dict[str, Any] = Field(default_factory=dict)
    user_question: str | None = None
    human_review_reason: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def _validate_control_fields(self) -> AgentDecision:
        if self.decision == DecisionType.CALL_TOOL and not self.tool_calls:
            raise ValueError("CALL_TOOL requires at least one tool call")
        if self.decision == DecisionType.CALL_TOOL:
            call_ids = [item.call_id for item in self.tool_calls if item.call_id]
            if len(call_ids) != len(set(call_ids)):
                raise ValueError("CALL_TOOL tool call IDs must be unique")
        if self.decision == DecisionType.HANDOFF and not self.next_agent:
            raise ValueError("HANDOFF requires next_agent")
        if self.decision == DecisionType.ASK_USER and not self.user_question:
            raise ValueError("ASK_USER requires user_question")
        if self.decision == DecisionType.HUMAN_REVIEW and not self.human_review_reason:
            raise ValueError("HUMAN_REVIEW requires human_review_reason")
        if self.decision != DecisionType.CALL_TOOL and self.tool_calls:
            raise ValueError("only CALL_TOOL decisions may contain tool_calls")
        return self
