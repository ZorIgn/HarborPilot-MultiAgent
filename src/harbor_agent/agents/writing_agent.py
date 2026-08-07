from __future__ import annotations

from harbor_agent.agents.base import BaseAgent
from harbor_agent.policies.tool_permissions import AGENT_TOOL_PERMISSIONS
from harbor_agent.runtime.decision import AgentDecision, DecisionType, ToolCallRequest
from harbor_agent.runtime.state import AgentState


class WritingWorkflowAgent(BaseAgent):
    """The specialized runtime WritingAgent; legacy drafting stays behind tools."""

    name = "WritingAgent"
    description = "Creates fact-bound writing plans using student story cards and official programme evidence."
    allowed_tools = AGENT_TOOL_PERMISSIONS[name]
    can_ask_user = True
    input_state_fields = ("normalized_profile", "selected_matches", "questionnaire", "story_cards")
    output_state_fields = ("story_cards", "writing_draft", "writing_ready")
    deterministic_boundaries = ("uses only student facts and official evidence", "unsupported claims remain review flags")

    def step(self, state: AgentState) -> AgentDecision:
        results = state.working_memory.get("tool_results", {})
        stories = results.get("build_story_cards")
        if not state.story_cards and stories is None:
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary="Retrieve bounded student/program evidence and build typed story cards.",
                tool_calls=[
                    ToolCallRequest(tool_name="retrieve_student_facts", arguments={}),
                    ToolCallRequest(tool_name="retrieve_program_evidence", arguments={}),
                    ToolCallRequest(tool_name="build_story_cards", arguments={}),
                ],
            )
        cards = list(stories.get("story_cards", [])) if stories else []
        if not state.story_cards and not cards and not results.get("build_writing_draft"):
            if bool((state.normalized_profile or {}).get("experiences")):
                return AgentDecision(
                    decision=DecisionType.CALL_TOOL,
                    reasoning_summary="Use existing student experience facts for a bounded first writing draft.",
                    tool_calls=[ToolCallRequest(tool_name="build_writing_draft", arguments={})],
                )
            return AgentDecision(
                decision=DecisionType.ASK_USER,
                reasoning_summary="The available questionnaire does not contain enough grounded writing material.",
                user_question="请补充可核实的课程、项目、科研或实习经历（问题、行动、结果、反思）。",
            )
        if not state.story_cards and cards:
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary="Story cards are available; inspect gaps before drafting.",
                state_patch={"story_cards": cards},
                tool_calls=[ToolCallRequest(tool_name="inspect_writing_gaps", arguments={})],
            )
        gaps = results.get("inspect_writing_gaps")
        if gaps and gaps.get("gaps") and not state.story_cards:
            return AgentDecision(
                decision=DecisionType.ASK_USER,
                reasoning_summary="The available questionnaire does not support a grounded writing draft.",
                user_question="请补充可核实的课程、项目、科研或实习经历（问题、行动、结果、反思）。",
            )
        draft = results.get("build_writing_draft")
        if not draft:
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary="Generate a fact-bound draft from story cards and selected programme evidence.",
                tool_calls=[ToolCallRequest(tool_name="build_writing_draft", arguments={})],
            )
        if not results.get("validate_writing_claims"):
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary="Validate the generated draft's fact bindings before handing it to the critic.",
                state_patch={"writing_draft": draft.get("draft"), "writing_ready": True},
                tool_calls=[ToolCallRequest(tool_name="validate_writing_claims", arguments={})],
            )
        return AgentDecision(
            decision=DecisionType.HANDOFF,
            reasoning_summary="Writing draft is ready for deterministic grounding review.",
            state_patch={"writing_draft": draft.get("draft"), "writing_ready": True},
            next_agent="SupervisorAgent",
        )
