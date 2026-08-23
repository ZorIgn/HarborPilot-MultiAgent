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
from harbor_agent.runtime.graph import SUPERVISOR_AGENT, can_handoff, can_terminate
from harbor_agent.runtime.limits import RuntimeLimits, record_agent_turn
from harbor_agent.runtime.state import (
    AgentState,
    WorkflowStatus,
    WorkflowTaskStatus,
    annotate_conflict,
    append_tool_result,
    apply_state_patch,
)
from harbor_agent.tools.base import ToolExecution
from harbor_agent.tools.registry import ToolRegistry

_RUNTIME_OWNED_STATE_FIELDS = {
    "workflow_id",
    "schema_version",
    "goal",
    "status",
    "current_agent",
    "previous_agent",
    "visited_agents",
    "step_count",
    "max_steps",
    "agent_turn_counts",
    "tool_call_count",
    "human_review_reason",
    "human_resolution",
    "pending_tool_approval",
    "active_tool_approval",
    "resolved_conflicts",
    "errors",
}
_SUPERVISOR_OWNED_STATE_FIELDS = {
    "tasks",
    "supervisor_replans",
    "user_question",
    "final_result",
}


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
            try:
                self._validate_decision_contract(agent, decision)
            except AgentDecisionValidationError as exc:
                tracer.emit(TraceEventType.ERROR, agent_name=agent.name, error=exc)
                failed = self._fail(state, str(exc))
                return finish(
                    failed,
                    AgentDecision(decision=DecisionType.FAIL, reasoning_summary="Agent decision violated its runtime contract."),
                )
            tracer.emit(TraceEventType.AGENT_DECISION, agent_name=agent.name, output_summary=f"{decision.decision.value}: {decision.reasoning_summary}")
            if decision.state_patch:
                state = apply_state_patch(
                    state,
                    decision.state_patch,
                    allowed_fields=agent.output_state_fields,
                )
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
                        if execution.approval_id:
                            state = apply_state_patch(
                                state,
                                {
                                    "pending_tool_approval": None,
                                    "active_tool_approval": None,
                                    "human_resolution": None,
                                    "human_review_reason": None,
                                },
                            )
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
                    return finish(
                        self._wait_human(
                            state,
                            str(exc),
                            pending_approval=exc.pending_approval,
                        ),
                        AgentDecision(
                            decision=DecisionType.HUMAN_REVIEW,
                            reasoning_summary="A high-risk tool is gated by an exact pending approval.",
                            human_review_reason=str(exc),
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - runtime boundary must persist unexpected tool failures.
                    tracer.emit(TraceEventType.ERROR, agent_name=agent.name, error=exc)
                    if state.active_tool_approval is not None:
                        state = apply_state_patch(
                            state,
                            {"active_tool_approval": None, "pending_tool_approval": None},
                        )
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
            policy = agent.step(state)
            model_tools = (
                {call.tool_name for call in policy.tool_calls}
                if policy.decision == DecisionType.CALL_TOOL
                else set()
            )
            tracer.emit(
                TraceEventType.LLM_REQUEST,
                agent_name=agent.name,
                model=getattr(agent.llm, "name", None),
                provider=getattr(agent.llm, "provider", None),
                input_summary=f"structured_decision; policy_tools={len(model_tools)}; attempt={attempt}",
                started_perf=started,
            )
            try:
                decision = agent.model_decision(
                    state,
                    self.registry.tool_schemas(model_tools),
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
                    if conversation is not None:
                        conversation.append(
                            {
                                "role": "user",
                                "content": (
                                    "The previous proposal was rejected by the runtime policy: "
                                    f"{str(exc)[:500]}. Return a fresh proposal using only the "
                                    "current policy envelope and no state_patch."
                                ),
                            }
                        )
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
            self._validate_model_policy(agent, policy, decision)
            return decision
        assert last_error is not None
        raise last_error

    @staticmethod
    def _validate_model_policy(
        agent: BaseAgent,
        policy: AgentDecision,
        decision: AgentDecision,
    ) -> None:
        """Keep model-driven Specialist calls an ordered policy subsequence.

        BaseAgent reduces a model proposal to exact policy tool names and
        arguments. This second executor-side assertion makes the invariant
        visible at the final execution boundary and preserves the deterministic
        tool order required by multi-step Specialists such as VerificationAgent.
        Supervisor routing is handled by its own route-options gate and may
        intentionally choose a non-primary safe route.
        """

        if agent.name == SUPERVISOR_AGENT:
            return
        if decision.decision != policy.decision:
            raise LLMStructuredOutputError(
                f"{agent.name} model decision {decision.decision.value} does not match "
                f"the deterministic policy action {policy.decision.value}"
            )
        if decision.state_patch != policy.state_patch:
            raise LLMStructuredOutputError(
                f"{agent.name} model state patch differs from the policy-owned patch"
            )
        if decision.decision != DecisionType.CALL_TOOL:
            return
        policy_keys = [agent._call_key(call) for call in policy.tool_calls]
        proposal_keys = [agent._call_key(call) for call in decision.tool_calls]
        cursor = 0
        for key in proposal_keys:
            try:
                cursor = policy_keys.index(key, cursor) + 1
            except ValueError as exc:
                raise LLMStructuredOutputError(
                    f"{agent.name} model tool calls are not an ordered policy subsequence"
                ) from exc

    @staticmethod
    def _validate_handoff(agent: BaseAgent, target: str | None) -> None:
        """Reject handoffs outside the agent declaration and capability graph."""

        if not target or target not in agent.possible_handoffs:
            raise AgentDecisionValidationError(f"{agent.name} cannot hand off to {target or '<missing target>'}")
        if not can_handoff(agent.name, target):
            raise AgentDecisionValidationError(f"handoff edge {agent.name} -> {target} is not registered")

    @classmethod
    def _validate_decision_contract(
        cls,
        agent: BaseAgent,
        decision: AgentDecision,
    ) -> None:
        """Enforce capabilities, terminal ownership and declared state outputs."""

        unauthorized = set(decision.state_patch) - set(agent.output_state_fields)
        if unauthorized:
            raise AgentDecisionValidationError(
                f"{agent.name} cannot write state fields: {sorted(unauthorized)}"
            )
        protected = set(decision.state_patch) & _RUNTIME_OWNED_STATE_FIELDS
        if agent.name != SUPERVISOR_AGENT:
            protected |= set(decision.state_patch) & _SUPERVISOR_OWNED_STATE_FIELDS
        if protected:
            raise AgentDecisionValidationError(
                f"{agent.name} cannot write runtime-owned state fields: {sorted(protected)}"
            )
        if decision.decision == DecisionType.COMPLETE and not can_terminate(agent.name):
            raise AgentDecisionValidationError(
                "only SupervisorAgent may complete the workflow"
            )
        if decision.decision == DecisionType.ASK_USER and not agent.can_ask_user:
            raise AgentDecisionValidationError(
                f"{agent.name} does not have the ASK_USER capability"
            )
        if decision.decision == DecisionType.HUMAN_REVIEW and not agent.can_request_human:
            raise AgentDecisionValidationError(
                f"{agent.name} does not have the HUMAN_REVIEW capability"
            )
        if decision.decision == DecisionType.HANDOFF:
            cls._validate_handoff(agent, decision.next_agent)
        if decision.decision == DecisionType.CALL_TOOL:
            forbidden = {
                call.tool_name for call in decision.tool_calls
                if call.tool_name not in agent.allowed_tools
            }
            if forbidden:
                raise AgentDecisionValidationError(
                    f"{agent.name} requested forbidden tools: {sorted(forbidden)}"
                )

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
    def _wait_human(
        state: AgentState,
        reason: str,
        *,
        pending_approval=None,
    ) -> AgentState:
        patch: dict[str, Any] = {
            "status": WorkflowStatus.WAITING_HUMAN.value,
            "human_review_reason": reason,
            "verification_conflicts": [
                annotate_conflict(item) for item in state.verification_conflicts
            ],
        }
        if pending_approval is not None:
            patch["pending_tool_approval"] = pending_approval
            patch["active_tool_approval"] = None
        return apply_state_patch(state, patch)

    @staticmethod
    def _complete(state: AgentState) -> AgentState:
        return apply_state_patch(state, {"status": WorkflowStatus.COMPLETED.value})

    @staticmethod
    def _fail(state: AgentState, message: str) -> AgentState:
        return apply_state_patch(state, {"status": WorkflowStatus.FAILED.value, "errors": [*state.errors, message[:1200]]})
