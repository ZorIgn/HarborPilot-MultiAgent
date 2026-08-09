from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from harbor_agent.observability.events import TraceEventType
from harbor_agent.observability.trace import RuntimeTracer
from harbor_agent.runtime.approval import canonical_tool_arguments
from harbor_agent.runtime.errors import (
    HumanReviewRequired,
    ToolArgumentValidationError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolPermissionError,
)
from harbor_agent.runtime.state import AgentState
from harbor_agent.services.tool_approval_store import (
    consume_tool_approval,
    create_pending_tool_approval,
)
from harbor_agent.tools.base import ToolDefinition, ToolExecution


class ToolRegistry:
    """Executes registered tools with validation, permission and trace boundaries."""

    def __init__(self, definitions: Iterable[ToolDefinition] | None = None) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        for definition in definitions or []:
            self.register(definition)

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"duplicate tool registration: {definition.name}")
        self._definitions[definition.name] = definition

    def names(self) -> set[str]:
        return set(self._definitions)

    def definition(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"tool not found: {name}") from exc

    def tool_schemas(self, allowed_tools: set[str]) -> list[dict[str, Any]]:
        from harbor_agent.llm.tool_schema import openai_tool_schema

        return [
            openai_tool_schema(item.name, item.description, item.input_model)
            for item in self._definitions.values()
            if item.name in allowed_tools
        ]

    def execute(
        self,
        *,
        agent_name: str,
        allowed_tools: set[str],
        state: AgentState,
        tool_name: str,
        arguments: dict[str, Any],
        tracer: RuntimeTracer,
        tool_call_id: str | None = None,
    ) -> ToolExecution:
        """Run one real tool call; all Tool Call/Result events originate here."""

        if tool_name not in allowed_tools:
            raise ToolPermissionError(f"{agent_name} is not allowed to call {tool_name}")
        definition = self.definition(tool_name)
        call_id = (
            f"tool_{uuid4().hex[:12]}"
            if definition.requires_human_review
            else tool_call_id or f"tool_{uuid4().hex[:12]}"
        )
        call_event = None
        if not definition.requires_human_review:
            # Record even a malformed low-risk attempt. Validation still runs
            # before any handler or human-approval capability is created.
            call_event = tracer.emit(
                TraceEventType.TOOL_CALL,
                agent_name=agent_name,
                tool_name=tool_name,
                tool_call_id=call_id,
                input_summary=_summary(arguments),
            )
        try:
            parsed = definition.input_model.model_validate(arguments)
        except ValidationError as exc:
            tracer.emit(
                TraceEventType.ERROR,
                agent_name=agent_name,
                tool_name=tool_name,
                tool_call_id=call_id,
                error=exc,
            )
            raise ToolArgumentValidationError(f"invalid arguments for {tool_name}: {exc}") from exc
        canonical_arguments = parsed.model_dump(mode="json")
        arguments_json, arguments_sha256 = canonical_tool_arguments(canonical_arguments)
        approval_id: str | None = None
        pending = None
        active = state.active_tool_approval
        if definition.requires_human_review and active is not None:
            if (
                active.workflow_id != state.workflow_id
                or active.agent_name != agent_name
                or active.tool_name != tool_name
                or active.arguments_sha256 != arguments_sha256
            ):
                raise ToolPermissionError(
                    "the active one-shot approval does not authorize this exact tool call"
                )
            call_id = active.tool_call_id
            approval_id = active.approval_id
        elif definition.requires_human_review:
            pending = create_pending_tool_approval(
                workflow_id=state.workflow_id,
                agent_name=agent_name,
                tool_name=tool_name,
                tool_call_id=call_id,
                arguments=canonical_arguments,
                arguments_json=arguments_json,
                arguments_sha256=arguments_sha256,
            )
            call_id = pending.tool_call_id
        if call_event is None:
            call_event = tracer.emit(
                TraceEventType.TOOL_CALL,
                agent_name=agent_name,
                tool_name=tool_name,
                tool_call_id=call_id,
                input_summary=_summary(canonical_arguments),
            )
        if definition.requires_human_review:
            if active is None:
                assert pending is not None
                raise HumanReviewRequired(
                    f"{tool_name} requires approval {pending.approval_id} for this exact call",
                    pending_approval=pending,
                )
            consume_tool_approval(
                active.approval_id,
                workflow_id=state.workflow_id,
                agent_name=agent_name,
                tool_name=tool_name,
                tool_call_id=call_id,
                arguments_sha256=arguments_sha256,
            )
        try:
            output = definition.handler(state, parsed)
            typed_output = definition.output_model.model_validate(output)
        except HumanReviewRequired:
            raise
        except Exception as exc:
            tracer.emit(
                TraceEventType.ERROR,
                agent_name=agent_name,
                tool_name=tool_name,
                tool_call_id=call_id,
                error=exc,
            )
            raise ToolExecutionError(f"{tool_name} failed: {type(exc).__name__}") from exc
        serialized = typed_output.model_dump(mode="json")
        result_event = tracer.emit(
            TraceEventType.TOOL_RESULT,
            agent_name=agent_name,
            tool_name=tool_name,
            tool_call_id=call_id,
            parent_event_id=call_event.event_id,
            output_summary=_summary(serialized),
        )
        _attach_execution_reference(
            serialized,
            workflow_id=state.workflow_id,
            agent_name=agent_name,
            tool_name=tool_name,
            tool_call_id=call_id,
            trace_event_ids=[call_event.event_id, result_event.event_id],
        )
        return ToolExecution(
            tool_name=tool_name,
            tool_call_id=call_id,
            approval_id=approval_id,
            output=serialized,
        )


def _attach_execution_reference(
    value: Any,
    *,
    workflow_id: str,
    agent_name: str,
    tool_name: str,
    tool_call_id: str,
    trace_event_ids: list[str],
) -> None:
    """Attach actual trace provenance to evidence returned by this tool call.

    Existing stored provenance wins: reading an evidence record must not claim
    that the read-only lookup created it. Newly produced field evidence is
    linked to the Tool Call and Tool Result events that actually produced it.
    """

    if isinstance(value, list):
        for item in value:
            _attach_execution_reference(
                item,
                workflow_id=workflow_id,
                agent_name=agent_name,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                trace_event_ids=trace_event_ids,
            )
        return
    if not isinstance(value, dict):
        return
    evidence_keys = {"program_id", "field_name", "source_type"}
    if evidence_keys.issubset(value) and not value.get("execution_ref"):
        value["execution_ref"] = {
            "workflow_id": workflow_id,
            "trace_event_ids": trace_event_ids,
            "produced_by_agent": agent_name,
            "produced_by_tool": tool_name,
            "tool_call_id": tool_call_id,
        }
    for item in value.values():
        _attach_execution_reference(
            item,
            workflow_id=workflow_id,
            agent_name=agent_name,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            trace_event_ids=trace_event_ids,
        )


def _summary(value: Any) -> str:
    text = str(value).replace("\n", " ")
    return text[:1200]
