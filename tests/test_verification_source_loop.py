from __future__ import annotations

from harbor_agent.agents.verification import VerificationAgent
from harbor_agent.runtime.decision import DecisionType
from harbor_agent.runtime.state import AgentState, WorkflowGoal, append_tool_result, apply_state_patch


def _state() -> AgentState:
    program_id = "program-a"
    return AgentState(
        workflow_id="verification_source_loop",
        goal=WorkflowGoal.APPLICATION_PLANNING,
        raw_profile={},
        normalized_profile={},
        assessment={},
        selected_program_ids=[program_id],
        fields_needing_verification={program_id: ["deadline"]},
        working_memory={
            "verification_source_fetch_enabled": True,
            "tool_results": {
                "get_program_trust_detail": {"program_id": program_id, "trust": {}},
                "list_missing_official_fields": {"program_id": program_id, "missing_fields": ["deadline"]},
                "compare_evidence_records": {"consistent": True, "conflicts": [], "human_review_required": False},
            },
        },
    )


def _apply(state: AgentState, decision) -> AgentState:
    return apply_state_patch(state, decision.state_patch) if decision.state_patch else state


def test_verification_source_refresh_is_a_real_multi_round_human_gated_loop() -> None:
    agent = VerificationAgent()
    state = _state()

    discovery = agent.step(state)
    assert discovery.decision == DecisionType.CALL_TOOL
    assert [call.tool_name for call in discovery.tool_calls] == ["discover_official_sources"]
    state = _apply(state, discovery)
    state = append_tool_result(state, "discover_official_sources", {"program_id": "program-a", "official_urls": ["https://example.edu/program"]})

    snapshot = agent.step(state)
    assert snapshot.decision == DecisionType.CALL_TOOL
    assert snapshot.tool_calls[0].tool_name == "snapshot_official_source"
    assert snapshot.tool_calls[0].arguments["dry_run"] is False
    state = _apply(state, snapshot)
    state = append_tool_result(state, "snapshot_official_source", {"program_id": "program-a", "url": "https://example.edu/program", "ok": True, "excerpt": "Deadline: 1 December 2027"})

    extraction = agent.step(state)
    assert extraction.decision == DecisionType.CALL_TOOL
    assert extraction.tool_calls[0].tool_name == "extract_program_fields"
    state = _apply(state, extraction)
    state = append_tool_result(state, "extract_program_fields", {"program_id": "program-a", "source_url": "https://example.edu/program", "fields": [{"field_name": "deadline", "value": "2027-12-01"}]})

    review = agent.step(state)
    assert review.decision == DecisionType.HUMAN_REVIEW
    assert "review" in (review.human_review_reason or "").lower()
    assert state.fields_needing_verification["program-a"] == ["deadline"]
    assert "official" not in state.verified_program_fields
    assert review.state_patch["working_memory"]["verification_sources"]["program-a"]["candidate_fields"]
