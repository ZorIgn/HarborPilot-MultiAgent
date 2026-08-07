from __future__ import annotations

from dataclasses import dataclass
from random import uniform
from time import perf_counter, sleep
from typing import Any

from harbor_agent.agents.base import BaseAgent
from harbor_agent.observability.events import TraceEventType
from harbor_agent.observability.trace import RuntimeTracer
from harbor_agent.runtime.context import append_tool_result as append_model_tool_result
from harbor_agent.runtime.decision import AgentDecision, DecisionType, ToolCallRequest
from harbor_agent.runtime.errors import (
    AgentDecisionValidationError,
    HumanReviewRequired,
    LLMStructuredOutputError,
    LLMTimeoutError,
    ToolExecutionError,
    WorkflowLimitExceeded,
)
from harbor_agent.runtime.graph import can_handoff
from harbor_agent.runtime.limits import RuntimeLimits, record_agent_turn
from harbor_agent.runtime.state import (
    AgentState,
    WorkflowStatus,
    WorkflowTaskStatus,
    append_tool_result,
    apply_state_patch,
)
from harbor_agent.tools.base import ToolExecution
from harbor_agent.tools.registry import ToolRegistry


@dataclass
class ExecutionOutcome:
    state: AgentState
    decision: AgentDecision


class AgentExecutor:
    """Runs real tool loops; agents never invoke a service or write state directly."""

    def __init__(self, registry: ToolRegistry, limits: RuntimeLimits) -> None:
        self.registry = registry
        self.limits = limits

    def execute_agent(self, agent: BaseAgent, state: AgentState, tracer: RuntimeTracer) -> ExecutionOutcome:
        turn_started = perf_counter()
        state = record_agent_turn(state, agent.name, self.limits)
        tracer.emit(TraceEventType.AGENT_STARTED, agent_name=agent.name, input_summary=f"turn={state.agent_turn_counts[agent.name]}")
        tracer.emit(TraceEventType.AGENT_START, agent_name=agent.name, input_summary=f"turn={state.agent_turn_counts[agent.name]}")

        def finish(final_state: AgentState, final_decision: AgentDecision) -> ExecutionOutcome:
            tracer.emit(
                TraceEventType.AGENT_END,
                agent_name=agent.name,
                output_summary=f"decision={final_decision.decision.value}; status={final_state.status.value}",
                started_perf=turn_started,
            )
            return ExecutionOutcome(final_state, final_decision)

        conversation = agent.build_model_messages(state) if agent.llm and agent.model_driven else None
        for _round in range(self.limits.max_tool_rounds_per_agent_turn):
            try:
                decision = self._next_decision(agent, state, tracer, conversation=conversation)
            except Exception as exc:  # noqa: BLE001 - runtime boundary must persist unexpected agent failures.
                tracer.emit(TraceEventType.ERROR, agent_name=agent.name, error=exc)
                return finish(self._fail(state, str(exc)), AgentDecision(decision=DecisionType.FAIL, reasoning_summary="Agent decision failed validation or provider execution."))
            if decision.decision == DecisionType.HANDOFF:
                try:
                    self._validate_handoff(agent, decision.next_agent)
                except AgentDecisionValidationError as exc:
                    tracer.emit(TraceEventType.ERROR, agent_name=agent.name, error=exc)
                    failed = self._fail(state, str(exc))
                    return finish(
                        failed,
                        AgentDecision(decision=DecisionType.FAIL, reasoning_summary="Agent requested an invalid handoff target."),
                    )
            tracer.emit(TraceEventType.AGENT_DECISION, agent_name=agent.name, output_summary=f"{decision.decision.value}: {decision.reasoning_summary}")
            if decision.state_patch:
                state = apply_state_patch(state, decision.state_patch)
            if decision.decision == DecisionType.CALL_TOOL:
                try:
                    if conversation is not None:
                        agent.append_model_tool_calls(conversation, decision)
                    for call in decision.tool_calls:
                        execution = self._execute_tool(
                            agent=agent,
                            state=state,
                            call=call,
                            tracer=tracer,
                        )
                        state = append_tool_result(state, execution.tool_name, execution.output)
                        if conversation is not None:
                            append_model_tool_result(
                                conversation,
                                tool_call_id=execution.tool_call_id,
                                output=execution.output,
                            )
                        state = apply_state_patch(state, {"tool_call_count": state.tool_call_count + 1})
                        if state.tool_call_count > self.limits.max_total_tool_calls:
                            raise WorkflowLimitExceeded("maximum total tool calls reached")
                    continue
                except HumanReviewRequired as exc:
                    return finish(self._wait_human(state, str(exc)), AgentDecision(decision=DecisionType.HUMAN_REVIEW, reasoning_summary="A high-risk tool is gated.", human_review_reason=str(exc)))
                except Exception as exc:  # noqa: BLE001 - runtime boundary must persist unexpected tool failures.
                    tracer.emit(TraceEventType.ERROR, agent_name=agent.name, error=exc)
                    return finish(self._fail(state, str(exc)), AgentDecision(decision=DecisionType.FAIL, reasoning_summary="Tool execution failed."))
            if decision.decision == DecisionType.ASK_USER:
                return finish(self._wait_user(state, decision.user_question or "请补充继续所需的信息。"), decision)
            if decision.decision == DecisionType.HUMAN_REVIEW:
                return finish(self._wait_human(state, decision.human_review_reason or "需要人工审核。"), decision)
            if decision.decision == DecisionType.COMPLETE:
                return finish(self._complete(state), decision)
            if decision.decision == DecisionType.FAIL:
                return finish(self._fail(state, decision.reasoning_summary), decision)
            if decision.decision == DecisionType.HANDOFF:
                tracer.emit(TraceEventType.HANDOFF, agent_name=agent.name, output_summary=f"to={decision.next_agent}; {decision.reasoning_summary}")
                return finish(self._complete_task(state, agent.name), decision)
        error = WorkflowLimitExceeded(f"{agent.name} exceeded maximum tool rounds per turn")
        tracer.emit(TraceEventType.ERROR, agent_name=agent.name, error=error)
        return finish(self._fail(state, str(error)), AgentDecision(decision=DecisionType.FAIL, reasoning_summary="Agent tool loop limit reached."))

    def _execute_tool(
        self,
        *,
        agent: BaseAgent,
        state: AgentState,
        call: ToolCallRequest,
        tracer: RuntimeTracer,
    ) -> ToolExecution:
        """Retry only a ToolDefinition that explicitly opts into transient recovery."""

        definition = self.registry.definition(call.tool_name)
        retries = (
            min(self.limits.max_tool_retries, max(0, int(definition.max_retries)))
            if definition.retryable
            else 0
        )
        for attempt in range(retries + 1):
            try:
                return self.registry.execute(
                    agent_name=agent.name,
                    allowed_tools=agent.allowed_tools,
                    state=state,
                    tool_name=call.tool_name,
                    arguments=call.arguments,
                    tracer=tracer,
                    tool_call_id=call.call_id,
                )
            except ToolExecutionError:
                if attempt >= retries:
                    raise
                tracer.emit(
                    TraceEventType.RETRY,
                    agent_name=agent.name,
                    tool_name=call.tool_name,
                    tool_call_id=call.call_id,
                    output_summary=f"tool retry {attempt + 1}/{retries}",
                )
                sleep((0.1 * (2**attempt)) + uniform(0, 0.05))
        raise AssertionError("tool retry loop exhausted without returning or raising")

    def _next_decision(
        self,
        agent: BaseAgent,
        state: AgentState,
        tracer: RuntimeTracer,
        *,
        conversation: list[dict[str, Any]] | None = None,
    ) -> AgentDecision:
        """Request a typed model decision and trace only actual provider activity."""

        if not agent.llm or not agent.model_driven:
            return agent.step(state)

        max_attempts = 3
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            started = perf_counter()
            tracer.emit(
                TraceEventType.LLM_REQUEST,
                agent_name=agent.name,
                model=getattr(agent.llm, "name", None),
                provider=getattr(agent.llm, "provider", None),
                input_summary=f"structured_decision; allowed_tools={len(agent.allowed_tools)}; attempt={attempt}",
                started_perf=started,
            )
            try:
                decision = agent.model_decision(
                    state,
                    self.registry.tool_schemas(agent.allowed_tools),
                    messages=conversation,
                )
            except (LLMTimeoutError, LLMStructuredOutputError) as exc:
                last_error = exc
                tracer.emit(
                    TraceEventType.ERROR,
                    agent_name=agent.name,
                    model=getattr(agent.llm, "name", None),
                    provider=getattr(agent.llm, "provider", None),
                    error=exc,
                    started_perf=started,
                )
                if attempt < max_attempts:
                    tracer.emit(
                        TraceEventType.RETRY,
                        agent_name=agent.name,
                        model=getattr(agent.llm, "name", None),
                        provider=getattr(agent.llm, "provider", None),
                        output_summary=f"model decision retry {attempt}/{max_attempts - 1}",
                    )
                    sleep((0.1 * (2 ** (attempt - 1))) + uniform(0, 0.05))
                    continue
                raise
            response = agent.last_llm_response
            tracer.emit(
                TraceEventType.LLM_RESPONSE,
                agent_name=agent.name,
                model=getattr(agent.llm, "name", None),
                provider=getattr(agent.llm, "provider", None),
                usage=response.usage if response else None,
                output_summary=(
                    f"tool_calls={len(response.tool_calls)}"
                    if response is not None
                    else "structured AgentDecision"
                ),
                started_perf=started,
            )
            if decision is None:
                raise LLMStructuredOutputError("model decision unexpectedly empty")
            return decision
        assert last_error is not None
        raise last_error

    @staticmethod
    def _validate_handoff(agent: BaseAgent, target: str | None) -> None:
        """Reject handoffs outside the agent declaration and capability graph."""

        if not target or target not in agent.possible_handoffs:
            raise AgentDecisionValidationError(f"{agent.name} cannot hand off to {target or '<missing target>'}")
        if not can_handoff(agent.name, target):
            raise AgentDecisionValidationError(f"handoff edge {agent.name} -> {target} is not registered")

    @staticmethod
    def _complete_task(state: AgentState, agent_name: str) -> AgentState:
        tasks = []
        completed = False
        for task in state.tasks:
            item = task.model_copy(deep=True)
            if not completed and item.assigned_agent == agent_name and item.status in {WorkflowTaskStatus.PENDING, WorkflowTaskStatus.RUNNING}:
                item.status = WorkflowTaskStatus.COMPLETED
                completed = True
            tasks.append(item.model_dump(mode="json"))
        return apply_state_patch(state, {"tasks": tasks})

    @staticmethod
    def _wait_user(state: AgentState, question: str) -> AgentState:
        return apply_state_patch(state, {"status": WorkflowStatus.WAITING_USER.value, "user_question": question, "human_review_reason": None})

    @staticmethod
    def _wait_human(state: AgentState, reason: str) -> AgentState:
        return apply_state_patch(state, {"status": WorkflowStatus.WAITING_HUMAN.value, "human_review_reason": reason})

    @staticmethod
    def _complete(state: AgentState) -> AgentState:
        return apply_state_patch(state, {"status": WorkflowStatus.COMPLETED.value})

    @staticmethod
    def _fail(state: AgentState, message: str) -> AgentState:
        return apply_state_patch(state, {"status": WorkflowStatus.FAILED.value, "errors": [*state.errors, message[:1200]]})
