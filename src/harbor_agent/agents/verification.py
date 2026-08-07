from __future__ import annotations

from copy import deepcopy

from harbor_agent.agents.base import BaseAgent
from harbor_agent.policies.tool_permissions import AGENT_TOOL_PERMISSIONS
from harbor_agent.runtime.decision import AgentDecision, DecisionType, ToolCallRequest
from harbor_agent.runtime.state import AgentState

def _source_refresh_step(
    *,
    state: AgentState,
    program_id: str,
    memory: dict,
    missing_fields: list[str],
    fields: dict,
    verified: dict,
    conflicts: list[dict],
    results: dict,
) -> AgentDecision | None:
    """Advance one explicit source-refresh phase without publishing evidence."""

    if not memory.get("verification_source_fetch_enabled") or not missing_fields:
        return None
    sessions = dict(memory.get("verification_sources", {}))
    session = dict(sessions.get(program_id, {}))

    def patch() -> dict:
        sessions[program_id] = session
        memory["verification_sources"] = sessions
        return {
            "fields_needing_verification": fields,
            "verified_program_fields": verified,
            "verification_conflicts": conflicts,
            "working_memory": memory,
        }

    discovery = results.get("discover_official_sources")
    if not session.get("discovery_requested"):
        session["discovery_requested"] = True
        return AgentDecision(
            decision=DecisionType.CALL_TOOL,
            reasoning_summary=f"Discover official source URLs for missing fields in {program_id}.",
            state_patch=patch(),
            tool_calls=[ToolCallRequest(tool_name="discover_official_sources", arguments={"program_id": program_id})],
        )
    if not isinstance(discovery, dict) or discovery.get("program_id") != program_id:
        session["source_attempted"] = True
        return None
    urls = [str(item) for item in discovery.get("official_urls", []) if item]
    source_url = str(session.get("source_url") or (urls[0] if urls else ""))
    if not source_url:
        session["source_attempted"] = True
        return None
    session["source_url"] = source_url
    snapshot = results.get("snapshot_official_source")
    if not session.get("snapshot_requested"):
        session["snapshot_requested"] = True
        return AgentDecision(
            decision=DecisionType.CALL_TOOL,
            reasoning_summary=f"Snapshot the official source for {program_id}; redirects and SSRF are checked by the source gateway.",
            state_patch=patch(),
            tool_calls=[
                ToolCallRequest(
                    tool_name="snapshot_official_source",
                    arguments={
                        "program_id": program_id,
                        "url": source_url,
                        "dry_run": bool(memory.get("verification_source_fetch_dry_run", False)),
                    },
                )
            ],
        )
    if not isinstance(snapshot, dict) or snapshot.get("program_id") not in {None, program_id} or snapshot.get("url") != source_url:
        return None
    if not snapshot.get("ok") or not snapshot.get("excerpt"):
        session["source_attempted"] = True
        return None
    extraction = results.get("extract_program_fields")
    if not session.get("extraction_requested"):
        session["extraction_requested"] = True
        return AgentDecision(
            decision=DecisionType.CALL_TOOL,
            reasoning_summary="Extract typed candidates from untrusted source text; candidates are not official until reviewed.",
            state_patch=patch(),
            tool_calls=[
                ToolCallRequest(
                    tool_name="extract_program_fields",
                    arguments={"program_id": program_id, "source_url": source_url, "source_text": snapshot.get("excerpt", "")},
                )
            ],
        )
    if not isinstance(extraction, dict) or extraction.get("program_id") != program_id or extraction.get("source_url") != source_url:
        session["source_attempted"] = True
        return None
    candidates = list(extraction.get("fields", []))
    if not candidates:
        session["source_attempted"] = True
        return None
    session["candidate_fields"] = candidates
    approved = set(memory.get("human_approved_tools", []))
    if not session.get("review_requested"):
        session["review_requested"] = True
        return AgentDecision(
            decision=DecisionType.HUMAN_REVIEW,
            reasoning_summary="Extracted official-source candidates require human approval before binding or publication.",
            state_patch=patch(),
            human_review_reason=f"{program_id}: review extracted fields from {source_url} before they can affect formal use.",
        )
    if "bind_source_to_program" not in approved:
        return AgentDecision(
            decision=DecisionType.HUMAN_REVIEW,
            reasoning_summary="Source binding remains gated until a reviewer explicitly approves it.",
            state_patch=patch(),
            human_review_reason=f"Approve or reject binding the extracted source fields for {program_id}.",
        )
    binding = results.get("bind_source_to_program")
    if not binding:
        return AgentDecision(
            decision=DecisionType.CALL_TOOL,
            reasoning_summary="Submit the approved source binding as a review proposal; it is not auto-published.",
            state_patch=patch(),
            tool_calls=[ToolCallRequest(tool_name="bind_source_to_program", arguments={"program_id": program_id, "source_url": source_url, "field_names": missing_fields})],
        )
    if "save_review_candidate" not in approved:
        return AgentDecision(
            decision=DecisionType.HUMAN_REVIEW,
            reasoning_summary="Saving a review candidate is also a human-gated mutation.",
            state_patch=patch(),
            human_review_reason=f"Approve saving the extracted candidate for {program_id} to the review queue.",
        )
    review = results.get("save_review_candidate")
    if not review:
        first = candidates[0] if isinstance(candidates[0], dict) else {}
        return AgentDecision(
            decision=DecisionType.CALL_TOOL,
            reasoning_summary="Save the approved candidate for reviewer publication; official verification remains gated.",
            state_patch=patch(),
            tool_calls=[
                ToolCallRequest(
                    tool_name="save_review_candidate",
                    arguments={
                        "program_id": program_id,
                        "field_name": str(first.get("field_name") or missing_fields[0]),
                        "proposed_value": str(first.get("value")) if first.get("value") is not None else None,
                        "reason": "Runtime source extraction candidate; human publication remains required.",
                    },
                )
            ],
        )
    session["source_attempted"] = True
    session["review_saved"] = True
    return None

class VerificationAgent(BaseAgent):
    name = "VerificationAgent"
    description = "Checks official-source readiness, evidence conflicts, and human-review requirements per programme."
    allowed_tools = AGENT_TOOL_PERMISSIONS[name]
    can_request_human = True
    input_state_fields = ("selected_program_ids", "fields_needing_verification", "verification_conflicts")
    output_state_fields = ("fields_needing_verification", "verified_program_fields", "verification_conflicts")
    deterministic_boundaries = ("community data never becomes official evidence", "conflicts are not overwritten by a model")

    def step(self, state: AgentState) -> AgentDecision:
        memory = deepcopy(state.working_memory)
        cursor = int(memory.get("verification_cursor", 0))
        selected = state.selected_program_ids
        if not selected:
            memory["verification_complete"] = True
            return AgentDecision(decision=DecisionType.HANDOFF, reasoning_summary="No programmes are selected for verification.", state_patch={"working_memory": memory}, next_agent="SupervisorAgent")
        if cursor >= len(selected):
            memory["verification_complete"] = True
            return AgentDecision(
                decision=DecisionType.HANDOFF,
                reasoning_summary="Verification completed for the selected programme set.",
                state_patch={"working_memory": memory},
                next_agent="SupervisorAgent",
            )
        program_id = selected[cursor]
        results = state.working_memory.get("tool_results", {})
        missing = results.get("list_missing_official_fields")
        comparison = results.get("compare_evidence_records")
        trust = results.get("get_program_trust_detail")
        if not (missing and comparison and trust and missing.get("program_id") == program_id):
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary=f"Verify official evidence for {program_id} through deterministic trust tools.",
                tool_calls=[
                    ToolCallRequest(tool_name="get_program_trust_detail", arguments={"program_id": program_id}),
                    ToolCallRequest(tool_name="list_missing_official_fields", arguments={"program_id": program_id}),
                    ToolCallRequest(tool_name="compare_evidence_records", arguments={"program_id": program_id}),
                ],
            )
        fields = dict(state.fields_needing_verification)
        fields[program_id] = list(missing.get("missing_fields", []))
        verified = dict(state.verified_program_fields)
        verified[program_id] = dict(trust.get("trust", {}))
        conflicts = list(state.verification_conflicts)
        conflicts.extend([dict(item, program_id=program_id) for item in comparison.get("conflicts", [])])
        source_decision = _source_refresh_step(
            state=state,
            program_id=program_id,
            memory=memory,
            missing_fields=list(missing.get("missing_fields", [])),
            fields=fields,
            verified=verified,
            conflicts=conflicts,
            results=results,
        )
        if source_decision is not None:
            return source_decision
        memory["verification_cursor"] = cursor + 1
        if cursor + 1 >= len(selected):
            memory["verification_complete"] = True
        if comparison.get("human_review_required"):
            return AgentDecision(
                decision=DecisionType.HUMAN_REVIEW,
                reasoning_summary="Official evidence conflicts require a human source decision.",
                state_patch={"fields_needing_verification": fields, "verified_program_fields": verified, "verification_conflicts": conflicts, "working_memory": memory},
                human_review_reason=f"{program_id} has conflicting official evidence; choose the authoritative record before publishing.",
            )
        return AgentDecision(
            decision=DecisionType.HANDOFF,
            reasoning_summary=f"Verified official-source readiness for {program_id}; supervisor will route the remaining work.",
            state_patch={"fields_needing_verification": fields, "verified_program_fields": verified, "verification_conflicts": conflicts, "working_memory": memory},
            next_agent="SupervisorAgent",
        )
