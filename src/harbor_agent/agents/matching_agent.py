from __future__ import annotations

from copy import deepcopy

from harbor_agent.agents.base import BaseAgent
from harbor_agent.models import ProgramMatch
from harbor_agent.policies.tool_permissions import AGENT_TOOL_PERMISSIONS
from harbor_agent.runtime.decision import AgentDecision, DecisionType, ToolCallRequest
from harbor_agent.runtime.state import AgentState
from harbor_agent.tools.matching_tools import materialize_match_dimensions


class MatchingAgent(BaseAgent):
    name = "MatchingAgent"
    description = "Separates admissions eligibility, preferences, financial feasibility and applicant-fit strategy."
    allowed_tools = AGENT_TOOL_PERMISSIONS[name]
    input_state_fields = ("normalized_profile", "assessment", "candidate_program_ids")
    output_state_fields = (
        "program_matches",
        "selected_program_ids",
        "blocked_program_ids",
        "selected_matches",
        "working_memory",
    )
    deterministic_boundaries = (
        "budget is not admissions eligibility",
        "LLM cannot change official requirements",
    )

    def step(self, state: AgentState) -> AgentDecision:
        results = state.working_memory.get("tool_results", {})
        dimension_tools = (
            "evaluate_admissions_eligibility",
            "evaluate_financial_feasibility",
            "evaluate_user_preference",
            "calculate_applicant_fit",
        )
        missing_dimensions = [name for name in dimension_tools if results.get(name) is None]
        if missing_dimensions:
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary="Evaluate each decision dimension separately before building a portfolio.",
                tool_calls=[
                    ToolCallRequest(
                        tool_name=name,
                        arguments={"program_ids": state.candidate_program_ids},
                    )
                    for name in missing_dimensions
                ],
            )
        fit = results.get("calculate_applicant_fit")
        if not state.program_matches:
            typed_matches = [ProgramMatch.model_validate(item) for item in fit.get("matches", [])]
            matches = [
                item.model_dump(mode="json")
                for item in materialize_match_dimensions(typed_matches, results)
            ]
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary="Fit was calculated; build a diversified portfolio from the real matching outputs.",
                state_patch={
                    "program_matches": {
                        str(item["program"]["id"]): item for item in matches if item.get("program")
                    }
                },
                tool_calls=[ToolCallRequest(tool_name="build_program_portfolio", arguments={})],
            )
        portfolio = results.get("build_program_portfolio")
        if not portfolio:
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary="Portfolio construction is pending.",
                tool_calls=[ToolCallRequest(tool_name="build_program_portfolio", arguments={})],
            )
        selected_ids = list(portfolio.get("selected_program_ids", []))
        explicit_ids = set(state.working_memory.get("explicit_selected_program_ids", []))
        memory = deepcopy(state.working_memory)
        if not selected_ids:
            financial = results.get("evaluate_financial_feasibility", {})
            hard_blocked = {
                str(item.get("program_id"))
                for item in financial.get("assessments", [])
                if item.get("blocks_user_selection")
            }
            if explicit_ids:
                selection_scope = explicit_ids
            else:
                selection_scope = [
                    program_id
                    for program_id, match in state.program_matches.items()
                    if isinstance(match, dict) and match.get("tier") != "not_recommended"
                ]
            financial_hard_cap_only = bool(selection_scope) and all(
                program_id in hard_blocked
                and isinstance(state.program_matches.get(program_id), dict)
                and state.program_matches[program_id].get("tier") != "not_recommended"
                for program_id in selection_scope
            )
            if financial_hard_cap_only:
                # This is a user preference constraint, not an admissions or
                # research failure. Preserve an explicit signal so the
                # Supervisor can request a budget choice instead of opening a
                # pointless research loop.
                memory["financial_hard_cap_blocked"] = True
                memory.pop("routing_hint", None)
            else:
                memory.pop("financial_hard_cap_blocked", None)
                if not explicit_ids:
                    # A completed matching pass with no actionable portfolio is a
                    # real dynamic edge back to research, rather than a silent empty
                    # recommendation or an invented admission result.
                    memory["routing_hint"] = {
                        "target": "ResearchAgent",
                        "reason": "Matching found no actionable portfolio; broaden or correct programme research.",
                    }
        return AgentDecision(
            decision=DecisionType.HANDOFF,
            reasoning_summary="Matching completed with separate eligibility, financial and preference inputs.",
            state_patch={
                "selected_program_ids": selected_ids,
                "blocked_program_ids": list(portfolio.get("blocked_program_ids", [])),
                "selected_matches": list(portfolio.get("portfolio", [])),
                "working_memory": memory,
            },
            next_agent="SupervisorAgent",
        )
