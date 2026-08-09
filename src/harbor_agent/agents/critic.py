from __future__ import annotations

from copy import deepcopy
from enum import Enum

from harbor_agent.agents.base import BaseAgent
from harbor_agent.policies.tool_permissions import AGENT_TOOL_PERMISSIONS
from harbor_agent.runtime.decision import AgentDecision, DecisionType, ToolCallRequest
from harbor_agent.runtime.state import AgentState


class CriticOutcome(str, Enum):
    PASS = "PASS"
    REPLAN_RESEARCH = "REPLAN_RESEARCH"
    REPLAN_MATCHING = "REPLAN_MATCHING"
    REVERIFY = "REVERIFY"
    REWRITE = "REWRITE"
    ASK_USER = "ASK_USER"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class CriticAgent(BaseAgent):
    name = "CriticAgent"
    description = "Audits recommendation, source and writing grounding and requests explicit replanning when needed."
    allowed_tools = AGENT_TOOL_PERMISSIONS[name]
    can_ask_user = True
    can_request_human = True
    input_state_fields = ("assessment", "selected_matches", "verification_conflicts", "timeline", "writing_draft")
    output_state_fields = ("working_memory",)
    deterministic_boundaries = ("formal gate is deterministic", "critic never overwrites conflicting official evidence")

    def step(self, state: AgentState) -> AgentDecision:
        if state.goal.value == "background_assessment" and state.assessment is not None:
            memory = deepcopy(state.working_memory)
            memory["critic_outcome"] = CriticOutcome.PASS.value
            return AgentDecision(decision=DecisionType.HANDOFF, reasoning_summary="Background assessment contains no formal programme claims to audit.", state_patch={"working_memory": memory}, next_agent="SupervisorAgent")
        results = state.working_memory.get("tool_results", {})
        required = ("validate_recommendation_consistency", "validate_source_grounding")
        if state.goal.value in {"writing", "full_application_plan"}:
            required = (*required, "validate_writing_grounding")
        if state.goal.value in {"application_planning", "full_application_plan"}:
            required = (*required, "formal_gate_check")
        if not all(results.get(item) for item in required):
            calls = [
                ToolCallRequest(tool_name=name, arguments={})
                for name in required
                if not results.get(name)
            ]
            return AgentDecision(decision=DecisionType.CALL_TOOL, reasoning_summary="Run deterministic critic gates against real runtime outputs.", tool_calls=calls)
        recommendation = results.get("validate_recommendation_consistency", {})
        source = results.get("validate_source_grounding", {})
        writing = results.get("validate_writing_grounding", {})
        memory = deepcopy(state.working_memory)
        if state.verification_conflicts:
            return AgentDecision(decision=DecisionType.HUMAN_REVIEW, reasoning_summary="Conflicting official evidence cannot be resolved automatically.", human_review_reason="Official programme evidence remains conflicted; a reviewer must select or reject the record.")
        if not recommendation.get("passed", True):
            memory["critic_outcome"] = CriticOutcome.REPLAN_MATCHING.value
        elif not source.get("passed", True):
            # A first failed grounding check must produce a real, bounded
            # Critic -> Verification reverify edge. After one retry, retain
            # the UNKNOWN gate instead of looping forever.
            attempts = int(state.working_memory.get("reverify_attempts", 0))
            missing_ids = [program_id for program_id, values in state.fields_needing_verification.items() if values]
            if attempts < 1 and missing_ids and (
                not state.working_memory.get("verification_complete")
                or state.working_memory.get("verification_source_fetch_enabled")
            ):
                memory["reverify_attempts"] = attempts + 1
                memory["reverify_target_program_id"] = missing_ids[0]
                memory["critic_outcome"] = CriticOutcome.REVERIFY.value
            else:
                memory["critic_outcome"] = CriticOutcome.PASS.value
        elif writing and not writing.get("passed", True):
            memory["critic_outcome"] = CriticOutcome.REWRITE.value
        else:
            memory["critic_outcome"] = CriticOutcome.PASS.value
        return AgentDecision(decision=DecisionType.HANDOFF, reasoning_summary=f"Critic outcome: {memory['critic_outcome']}.", state_patch={"working_memory": memory}, next_agent="SupervisorAgent")
