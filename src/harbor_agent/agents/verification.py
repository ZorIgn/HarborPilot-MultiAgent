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
        patch()
        return None
    urls = [str(item) for item in discovery.get("official_urls", []) if item]
    source_url = str(session.get("source_url") or (urls[0] if urls else ""))
    if not source_url:
        session["source_attempted"] = True
        patch()
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
        patch()
        return None
    if not snapshot.get("snapshot_id") or not snapshot.get("page_hash"):
        # A successful HTTP response is not an auditable source observation
        # until it has an immutable snapshot identity and content hash. Stop
        # this refresh attempt before extraction or human approval rather than
        # constructing an approval request that cannot be bound exactly.
        session["source_attempted"] = True
        patch()
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
        patch()
        return None
    candidates = list(extraction.get("fields", []))
    if not candidates:
        session["source_attempted"] = True
        patch()
        return None
    session["candidate_fields"] = candidates
    candidate_field_names = list(
        dict.fromkeys(
            str(item.get("field_name"))
            for item in candidates
            if isinstance(item, dict) and item.get("field_name")
        )
    )
    if not candidate_field_names:
        session["source_attempted"] = True
        patch()
        return None
    binding = results.get("bind_source_to_program")
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    page_hash = str(snapshot.get("page_hash") or "")
    if not isinstance(binding, dict) or binding.get("program_id") != program_id or binding.get("source_url") != source_url or binding.get("snapshot_id") != snapshot_id or binding.get("page_hash") != page_hash:
        return AgentDecision(
            decision=DecisionType.CALL_TOOL,
            reasoning_summary="Submit the exact source binding to the one-shot human approval gate.",
            state_patch=patch(),
            tool_calls=[ToolCallRequest(tool_name="bind_source_to_program", arguments={"program_id": program_id, "source_url": source_url, "field_names": candidate_field_names, "snapshot_id": snapshot_id, "page_hash": page_hash})],
        )
    review = results.get("save_review_candidate")
    saved_fields = set(session.get("saved_candidate_fields", []))
    if (
        isinstance(review, dict)
        and review.get("program_id") == program_id
        and review.get("persisted")
        and review.get("field_name")
    ):
        saved_fields.add(str(review["field_name"]))
        session["saved_candidate_fields"] = sorted(saved_fields)
    next_candidate = next(
        (
            item
            for item in candidates
            if isinstance(item, dict)
            and str(item.get("field_name") or "") not in saved_fields
        ),
        None,
    )
    if next_candidate is not None:
        return AgentDecision(
            decision=DecisionType.CALL_TOOL,
            reasoning_summary="Persist the next exact candidate for reviewer publication; official verification remains gated.",
            state_patch=patch(),
            tool_calls=[
                ToolCallRequest(
                    tool_name="save_review_candidate",
                    arguments={
                        "program_id": program_id,
                        "field_name": str(next_candidate.get("field_name")),
                        "proposed_value": str(next_candidate.get("value")) if next_candidate.get("value") is not None else None,
                        "reason": "Runtime source extraction candidate; human publication remains required.",
                        "snapshot_id": snapshot_id,
                        "page_hash": page_hash,
                    },
                )
            ],
        )
    session["source_attempted"] = True
    session["review_saved"] = True
    sessions[program_id] = session
    memory["verification_sources"] = sessions
    return None

class VerificationAgent(BaseAgent):
    name = "VerificationAgent"
    description = "Checks official-source readiness, evidence conflicts, and human-review requirements per programme."
    allowed_tools = AGENT_TOOL_PERMISSIONS[name]
    can_request_human = True
    input_state_fields = ("selected_program_ids", "fields_needing_verification", "verification_conflicts")
    output_state_fields = ("fields_needing_verification", "verified_program_fields", "verification_conflicts", "working_memory")
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
        required = {
            "get_program_trust_detail": trust,
            "list_missing_official_fields": missing,
            "compare_evidence_records": comparison,
        }
        missing_tools = [
            name
            for name, result in required.items()
            if not isinstance(result, dict) or result.get("program_id") != program_id
        ]
        if missing_tools:
            return AgentDecision(
                decision=DecisionType.CALL_TOOL,
                reasoning_summary=f"Verify official evidence for {program_id} through deterministic trust tools.",
                tool_calls=[
                    ToolCallRequest(tool_name=name, arguments={"program_id": program_id})
                    for name in missing_tools
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
