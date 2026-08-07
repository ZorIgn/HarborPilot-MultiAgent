from __future__ import annotations

from copy import deepcopy
from typing import ClassVar
from uuid import uuid4

from pydantic import BaseModel

from harbor_agent.agents.base import BaseAgent
from harbor_agent.llm.response import LLMResponse, LLMToolCall, LLMUsage
from harbor_agent.observability.events import TraceEventType
from harbor_agent.observability.trace import RuntimeTracer
from harbor_agent.runtime.decision import AgentDecision, DecisionType
from harbor_agent.runtime.executor import AgentExecutor
from harbor_agent.runtime.limits import RuntimeLimits
from harbor_agent.runtime.state import AgentState, WorkflowGoal
from harbor_agent.services.agent_runtime import list_runtime_trace_events
from harbor_agent.tools.base import ToolDefinition
from harbor_agent.tools.registry import ToolRegistry


class EchoInput(BaseModel):
    value: str


class EchoOutput(BaseModel):
    echoed: str


class RecordingProvider:
    name = "recording-model"
    provider = "test-provider"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.messages: list[list[dict]] = []

    def complete(self, *, messages, tools=None, response_model=None):
        self.messages.append(deepcopy(messages))
        return self.responses.pop(0)


class ToolLoopAgent(BaseAgent):
    name = "ToolLoopAgent"
    description = "test agent that must observe a tool result"
    allowed_tools: ClassVar[set[str]] = {"echo_tool"}

    def step(self, state: AgentState) -> AgentDecision:
        raise AssertionError("model-driven agent must not use deterministic step")


def _registry() -> ToolRegistry:
    def echo(_: AgentState, request: EchoInput) -> EchoOutput:
        return EchoOutput(echoed=request.value)

    return ToolRegistry(
        [
            ToolDefinition(
                name="echo_tool",
                description="Echo a test value.",
                input_model=EchoInput,
                output_model=EchoOutput,
                handler=echo,
            )
        ]
    )


def test_model_tool_loop_preserves_call_id_and_tool_history() -> None:
    provider = RecordingProvider(
        [
            LLMResponse(
                tool_calls=[
                    LLMToolCall(
                        call_id="call_provider_42",
                        name="echo_tool",
                        arguments={"value": "hello"},
                    )
                ],
                usage=LLMUsage(prompt_tokens=5, completion_tokens=2),
                model="recording-model",
                provider="test-provider",
            ),
            LLMResponse(
                json_content={
                    "decision": "HANDOFF",
                    "reasoning_summary": "The tool result was observed.",
                    "next_agent": "SupervisorAgent",
                },
                usage=LLMUsage(prompt_tokens=9, completion_tokens=3),
                model="recording-model",
                provider="test-provider",
            ),
        ]
    )
    workflow_id = f"tool_history_{uuid4().hex}"
    state = AgentState(workflow_id=workflow_id, goal=WorkflowGoal.BACKGROUND_ASSESSMENT)
    outcome = AgentExecutor(_registry(), RuntimeLimits()).execute_agent(
        ToolLoopAgent(llm=provider, model_driven=True),
        state,
        RuntimeTracer(workflow_id),
    )

    assert outcome.decision.decision == DecisionType.HANDOFF
    assert len(provider.messages) == 2
    second_history = provider.messages[1]
    assert [item["role"] for item in second_history] == ["system", "user", "assistant", "tool"]
    assistant = second_history[2]
    assert assistant["tool_calls"][0]["id"] == "call_provider_42"
    assert assistant["tool_calls"][0]["function"]["name"] == "echo_tool"
    assert assistant["tool_calls"][0]["function"]["arguments"] == '{"value":"hello"}'
    tool_result = second_history[3]
    assert tool_result["tool_call_id"] == "call_provider_42"
    assert tool_result["content"] == '{"echoed":"hello"}'

    events = list_runtime_trace_events(workflow_id)
    tool_events = [item for item in events if item["event_type"] in {TraceEventType.TOOL_CALL.value, TraceEventType.TOOL_RESULT.value}]
    assert [item["tool_call_id"] for item in tool_events] == ["call_provider_42", "call_provider_42"]


def test_executor_rejects_handoff_outside_declared_graph() -> None:
    class InvalidHandoffAgent(BaseAgent):
        name = "AssessmentAgent"
        description = "test invalid handoff"
        allowed_tools: ClassVar[set[str]] = set()
        possible_handoffs: ClassVar[set[str]] = {"ResearchAgent"}

        def step(self, state: AgentState) -> AgentDecision:
            return AgentDecision(
                decision=DecisionType.HANDOFF,
                reasoning_summary="invalid direct handoff",
                next_agent="ResearchAgent",
            )

    workflow_id = f"invalid_handoff_{uuid4().hex}"
    state = AgentState(workflow_id=workflow_id, goal=WorkflowGoal.BACKGROUND_ASSESSMENT)
    outcome = AgentExecutor(ToolRegistry(), RuntimeLimits()).execute_agent(
        InvalidHandoffAgent(), state, RuntimeTracer(workflow_id)
    )

    assert outcome.decision.decision == DecisionType.FAIL
    assert outcome.state.status.value == "FAILED"
    assert any("handoff edge" in error for error in outcome.state.errors)
