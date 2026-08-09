from __future__ import annotations

from harbor_agent.agents.base import BaseAgent
from harbor_agent.policies.tool_permissions import AGENT_TOOL_PERMISSIONS
from harbor_agent.runtime.decision import AgentDecision, DecisionType, ToolCallRequest
from harbor_agent.runtime.state import AgentState


class AssessmentAgent(BaseAgent):
    name = "AssessmentAgent"
    description = "Normalizes the profile, detects required gaps, and creates an evidence-backed assessment."
    allowed_tools = AGENT_TOOL_PERMISSIONS[name]
    can_ask_user = True
    input_state_fields = ("raw_profile", "user_request")
    output_state_fields = ("normalized_profile", "assessment", "evidence_review", "missing_profile_fields")
    deterministic_boundaries = ("GPA and language rules are tool-owned", "never invent missing profile facts")

    def step(self, state: AgentState) -> AgentDecision:
        results = state.working_memory.get("tool_results", {})
        if state.normalized_profile is None:
            raw_gaps = results.get("find_profile_gaps")
            if raw_gaps is None:
                return AgentDecision(
                    decision=DecisionType.CALL_TOOL,
                    reasoning_summary="Inspect required raw-profile fields before normalization so missing data becomes a resumable question.",
                    tool_calls=[ToolCallRequest(tool_name="find_profile_gaps", arguments={})],
                )
            raw_critical = list(raw_gaps.get("critical_missing_fields", []))
            if raw_critical:
                return AgentDecision(
                    decision=DecisionType.ASK_USER,
                    reasoning_summary="The submitted profile is missing fields required for deterministic normalization.",
                    user_question="请补充以下关键信息后继续：" + "、".join(raw_critical[:4]),
                    confidence=0.98,
                )
            normalized = results.get("normalize_profile")
            if normalized:
                required_tools = (
                    "find_profile_gaps",
                    "inspect_evidence_readiness",
                    "calculate_profile_assessment",
                    "detect_background_gap",
                )
                return AgentDecision(
                    decision=DecisionType.CALL_TOOL,
                    reasoning_summary="The profile is normalized; now inspect gaps, evidence readiness and assessment.",
                    state_patch={"normalized_profile": normalized},
                    tool_calls=[
                        ToolCallRequest(tool_name=name, arguments={})
                        for name in required_tools
                        if results.get(name) is None
                    ],
                )
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary="A normalized profile is required before any assessment decision.",
                tool_calls=[ToolCallRequest(tool_name="normalize_profile", arguments={})],
            )

        gap_result = results.get("find_profile_gaps") or results.get("inspect_profile_gaps")
        evidence = results.get("inspect_evidence_readiness")
        assessment = results.get("calculate_profile_assessment")
        required_tools = (
            "find_profile_gaps",
            "inspect_evidence_readiness",
            "calculate_profile_assessment",
            "detect_background_gap",
        )
        missing_tools = [name for name in required_tools if results.get(name) is None]
        if missing_tools:
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary="Complete the missing deterministic assessment checks.",
                tool_calls=[
                    ToolCallRequest(tool_name=name, arguments={})
                    for name in missing_tools
                ],
            )
        missing = list(gap_result.get("missing_fields", []))
        patch = {"missing_profile_fields": missing, "evidence_review": evidence, "assessment": assessment}
        critical = list(gap_result.get("critical_missing_fields", []))
        language = (state.normalized_profile or {}).get("language", {})
        if language.get("test") == "NONE" or language.get("overall") is None:
            critical.append("语言成绩")
        critical = list(dict.fromkeys(critical))

        if critical and state.goal.value != "background_assessment":
            return AgentDecision(
                decision=DecisionType.ASK_USER,
                reasoning_summary="Formal recommendation requires missing profile information.",
                state_patch=patch,
                user_question="请补充以下关键信息后继续：" + "、".join(critical[:4]),
                confidence=0.95,
            )
        return AgentDecision(
            decision=DecisionType.HANDOFF,
            reasoning_summary="Profile assessment is complete and ready for supervisor routing.",
            state_patch=patch,
            next_agent="SupervisorAgent",
        )
