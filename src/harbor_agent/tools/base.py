from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Type

from pydantic import BaseModel, ConfigDict

from harbor_agent.runtime.state import AgentState


class EmptyToolInput(BaseModel):
    """Use for a tool whose typed input comes entirely from shared state."""

    model_config = ConfigDict(extra="forbid")


class ToolExecution(BaseModel):
    """Normalized, serializable result returned by the registry."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    tool_call_id: str
    output: dict[str, Any]


ToolHandler = Callable[[AgentState, BaseModel], BaseModel]


@dataclass(frozen=True)
class ToolDefinition:
    """A deterministic capability exposed to an agent through the registry."""

    name: str
    description: str
    input_model: Type[BaseModel]
    output_model: Type[BaseModel]
    handler: ToolHandler
    requires_human_review: bool = False
    max_retries: int = 0
    retryable: bool = False
