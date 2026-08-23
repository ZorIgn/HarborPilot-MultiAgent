from __future__ import annotations

from copy import deepcopy
from enum import Enum

from harbor_agent.agents.base import BaseAgent
from harbor_agent.models import CriticReadiness
from harbor_agent.policies.tool_permissions import AGENT_TOOL_PERMISSIONS
from harbor_agent.runtime.decision import AgentDecision, DecisionType, ToolCallRequest
from harbor_agent.runtime.state import AgentState


class CriticOutcome(str, Enum):
    PASS = "PASS"
    PRELIMINARY_COMPLETE = "PRELIMINARY_COMPLETE"
    BLOCKED = "BLOCKED"
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
            _set_readiness(
                memory,
                CriticReadiness.PRELIMINARY_COMPLETE,
                [],
            )
            return AgentDecision(
                decision=DecisionType.HANDOFF,
                reasoning_summary="Background assessment contains no formal programme claims to audit.",
                state_patch={"working_memory": memory},
                next_agent="SupervisorAgent",
            )
        results = state.working_memory.get("tool_results", {})
        required = ("validate_recommendation_consistency", "validate_source_grounding")
        if state.goal.value in {"writing", "full_application_plan"}:
            required = (*required, "validate_writing_grounding")
        if state.goal.value in {
            "program_recommendation",
            "application_planning",
            "full_application_plan",
        }:
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
        formal = results.get("formal_gate_check", {})
        memory = deepcopy(state.working_memory)
        if state.verification_conflicts:
            _set_readiness(
                memory,
                CriticReadiness.BLOCKED,
                [
                    "Official programme evidence remains conflicted; a reviewer must select or reject the record."
                ],
            )
            return AgentDecision(
                decision=DecisionType.HUMAN_REVIEW,
                reasoning_summary="Conflicting official evidence cannot be resolved automatically.",
                state_patch={"working_memory": memory},
                human_review_reason="Official programme evidence remains conflicted; a reviewer must select or reject the record.",
            )
        if recommendation.get("passed") is not True:
            _set_readiness(
                memory,
                CriticReadiness.BLOCKED,
                _gate_blockers(
                    "validate_recommendation_consistency",
                    recommendation,
                    "Recommendation consistency gate did not pass.",
                ),
            )
            memory["critic_outcome"] = CriticOutcome.REPLAN_MATCHING.value
        elif source.get("passed") is not True:
            # A first failed grounding check must produce a real, bounded
            # Critic -> Verification reverify edge. After one retry, retain a
            # structured BLOCKED readiness result instead of falsely passing.
            attempts = int(state.working_memory.get("reverify_attempts", 0))
            missing_ids = [program_id for program_id, values in state.fields_needing_verification.items() if values]
            if attempts < 1 and missing_ids and (
                not state.working_memory.get("verification_complete")
                or state.working_memory.get("verification_source_fetch_enabled")
            ):
                memory["reverify_attempts"] = attempts + 1
                memory["reverify_target_program_id"] = missing_ids[0]
                memory["critic_outcome"] = CriticOutcome.REVERIFY.value
                _set_readiness(
                    memory,
                    CriticReadiness.BLOCKED,
                    _source_blockers(state, source),
                )
            else:
                # A source failure must never be represented as PASS.  A
                # catalogue/research result can still be delivered as an
                # explicitly preliminary artifact for the two exploration
                # goals, while formal planning and writing remain blocked.
                if _allows_preliminary_delivery(state):
                    memory["critic_outcome"] = CriticOutcome.PRELIMINARY_COMPLETE.value
                    _set_readiness(
                        memory,
                        CriticReadiness.PRELIMINARY_COMPLETE,
                        _source_blockers(state, source),
                    )
                else:
                    memory["critic_outcome"] = CriticOutcome.BLOCKED.value
                    _set_readiness(
                        memory,
                        CriticReadiness.BLOCKED,
                        _source_blockers(state, source),
                    )
        elif writing and (
            writing.get("passed") is not True
            or state.writing_ready is not True
            or writing.get("details", {}).get("claim_grounding_ready") is not True
        ):
            _set_readiness(
                memory,
                CriticReadiness.BLOCKED,
                _gate_blockers(
                    "validate_writing_grounding",
                    writing,
                    "Writing grounding gate did not pass.",
                ),
            )
            memory["critic_outcome"] = CriticOutcome.REWRITE.value
        elif formal and formal.get("passed") is not True:
            blockers = _gate_blockers(
                "formal_gate_check",
                formal,
                "Formal-use gate did not pass.",
            )
            if _allows_preliminary_delivery(state):
                memory["critic_outcome"] = CriticOutcome.PRELIMINARY_COMPLETE.value
                _set_readiness(memory, CriticReadiness.PRELIMINARY_COMPLETE, blockers)
            else:
                _set_readiness(memory, CriticReadiness.BLOCKED, blockers)
                memory["critic_outcome"] = CriticOutcome.BLOCKED.value
        else:
            _set_readiness(memory, CriticReadiness.FORMAL_PASS, [])
            memory["critic_outcome"] = CriticOutcome.PASS.value
        return AgentDecision(decision=DecisionType.HANDOFF, reasoning_summary=f"Critic outcome: {memory['critic_outcome']}.", state_patch={"working_memory": memory}, next_agent="SupervisorAgent")


def _set_readiness(
    memory: dict,
    readiness: CriticReadiness,
    blockers: list[str],
) -> None:
    """Persist an explicit terminal/readiness classification for Supervisor.

    ``critic_outcome`` remains the routing operation for compatibility (for
    example ``REVERIFY`` or ``REWRITE``), while ``critic_readiness`` answers a
    different question: whether the current result is formally usable,
    preliminary-only, or blocked.  Keeping both prevents an operational retry
    from being mistaken for a successful formal review.
    """

    memory["critic_readiness"] = readiness.value
    memory["readiness_level"] = readiness.value
    memory["critic_blockers"] = list(dict.fromkeys(str(item) for item in blockers if str(item).strip()))


def _gate_blockers(name: str, result: object, fallback: str) -> list[str]:
    """Extract structured blockers without trusting a missing ``passed`` key."""

    payload = result if isinstance(result, dict) else {}
    blockers = payload.get("blockers")
    if isinstance(blockers, list):
        values = [str(item).strip() for item in blockers if str(item).strip()]
        if values:
            return values
    return [f"{name}: {fallback}"]


def _source_blockers(state: AgentState, source: object) -> list[str]:
    """Report source-gate blockers even when field-level state is empty."""

    blockers = _gate_blockers(
        "validate_source_grounding",
        source,
        "Official source grounding gate did not pass.",
    )
    missing = [
        f"{program_id}: official fields missing ({', '.join(fields)})"
        for program_id, fields in state.fields_needing_verification.items()
        if fields
    ]
    return list(dict.fromkeys([*blockers, *missing]))


def _allows_preliminary_delivery(state: AgentState) -> bool:
    """Return whether the requested artifact has a safe non-formal variant.

    Candidate selection and preparation-only timelines remain useful in the
    default offline/mock environment, provided the result is explicitly marked
    ``PRELIMINARY_COMPLETE`` and carries its missing-source blockers.  Formal
    application delivery and programme-specific writing do not have that
    relaxation: they stay blocked until the relevant DecisionFacts exist.
    """

    return state.goal.value in {"program_recommendation", "application_planning"}
