from __future__ import annotations

from harbor_agent.agents.base import BaseAgent
from harbor_agent.models import WritingDraft
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
            prerequisites = (
                "retrieve_student_facts",
                "retrieve_program_evidence",
            )
            missing_prerequisites = [
                name for name in prerequisites if results.get(name) is None
            ]
            if missing_prerequisites:
                return AgentDecision(
                    decision=DecisionType.CALL_TOOL,
                    reasoning_summary="Retrieve bounded student and programme evidence before building story cards.",
                    tool_calls=[
                        ToolCallRequest(tool_name=name, arguments={})
                        for name in missing_prerequisites
                    ],
                )
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary="The evidence prerequisites are ready; build typed story cards.",
                tool_calls=[ToolCallRequest(tool_name="build_story_cards", arguments={})],
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
                # Validation is a separate executor turn.  A draft is never
                # ready merely because the validator was scheduled.
                state_patch={
                    "writing_draft": _draft_with_claim_validation(
                        draft.get("draft"),
                        {},
                        claim_grounding_ready=False,
                        fallback_blockers=["ClaimGraph 验证尚未完成，文书不能标记为 ready。"],
                    ),
                    "writing_ready": False,
                },
                tool_calls=[ToolCallRequest(tool_name="validate_writing_claims", arguments={})],
            )
        validation = results.get("validate_writing_claims") or {}
        # Require both structured flags.  In particular, do not treat the
        # presence of a result, a non-empty graph, or legacy review_flags as a
        # successful grounding decision.
        grounded = validation.get("grounded") is True
        passed = validation.get("passed") is True
        blockers = validation.get("blockers") or []
        unsupported = validation.get("unsupported_claims") or []
        if not (grounded and passed and not blockers and not unsupported):
            return AgentDecision(
                decision=DecisionType.HANDOFF,
                reasoning_summary="Writing claim validation is blocked; keep writing_ready=false and ask Supervisor/Critic to rewrite.",
                state_patch={
                    "writing_draft": _draft_with_claim_validation(
                        draft.get("draft"),
                        validation,
                        claim_grounding_ready=False,
                        fallback_blockers=["ClaimGraph 未通过；不能把文书标记为 ready。"],
                    ),
                    "writing_ready": False,
                },
                next_agent="SupervisorAgent",
            )
        return AgentDecision(
            decision=DecisionType.HANDOFF,
            reasoning_summary="Writing draft is ready for deterministic grounding review.",
            state_patch={
                "writing_draft": _draft_with_claim_validation(
                    draft.get("draft"),
                    validation,
                    claim_grounding_ready=True,
                ),
                "writing_ready": True,
            },
            next_agent="SupervisorAgent",
        )


def _draft_with_claim_validation(
    raw_draft: object,
    validation: dict,
    *,
    claim_grounding_ready: bool,
    fallback_blockers: list[str] | None = None,
) -> dict:
    """Attach structured validation metadata without trusting review prose.

    ``formal_use_ready`` deliberately stays false here.  The Critic/Supervisor
    owns the final delivery decision after source and formal gates complete.
    """

    draft = WritingDraft.model_validate(raw_draft)
    payload = draft.model_dump(mode="json")
    graph = validation.get("graph") if isinstance(validation, dict) else None
    blockers = validation.get("blockers") if isinstance(validation, dict) else None
    if not isinstance(blockers, list):
        blockers = []
    blockers = [str(item).strip() for item in blockers if str(item).strip()]
    if not blockers and fallback_blockers:
        blockers = list(fallback_blockers)
    payload.update(
        {
            "claim_graph": graph,
            "claim_grounding_ready": claim_grounding_ready,
            "formal_use_ready": False,
            "formal_blockers": list(dict.fromkeys(blockers)),
        }
    )
    return payload
