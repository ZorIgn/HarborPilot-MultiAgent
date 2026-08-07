from __future__ import annotations

import json
from typing import Any

from harbor_agent.runtime.state import AgentState, compact_value


def build_agent_context(agent_name: str, state: AgentState) -> dict[str, Any]:
    """Return the smallest context each agent needs; never dump all state."""

    common = {
        "workflow_id": state.workflow_id,
        "goal": state.goal.value,
        "user_request": state.user_request[:800],
        "selected_program_ids": state.selected_program_ids[:20],
    }
    if agent_name == "AssessmentAgent":
        return {**common, "raw_profile": compact_value(state.raw_profile), "missing_profile_fields": state.missing_profile_fields}
    if agent_name == "ResearchAgent":
        return {**common, "profile": compact_value(state.normalized_profile), "candidate_program_ids": state.candidate_program_ids[:40]}
    if agent_name == "MatchingAgent":
        return {**common, "profile": compact_value(state.normalized_profile), "assessment": compact_value(state.assessment), "candidates": state.candidate_program_ids[:40]}
    if agent_name == "VerificationAgent":
        return {**common, "selected_program_ids": state.selected_program_ids[:20], "fields_needing_verification": compact_value(state.fields_needing_verification), "conflicts": compact_value(state.verification_conflicts)}
    if agent_name == "PlanningAgent":
        return {**common, "selected_matches": compact_value(state.selected_matches), "verified_fields": compact_value(state.verified_program_fields)}
    if agent_name == "WritingAgent":
        return {**common, "profile": compact_value(state.normalized_profile), "story_cards": compact_value(state.story_cards), "selected_matches": compact_value(state.selected_matches), "document_type": state.document_type}
    if agent_name == "CriticAgent":
        return {**common, "assessment": compact_value(state.assessment), "matches": compact_value(state.selected_matches), "timeline_ready": state.timeline_ready, "writing_ready": state.writing_ready, "conflicts": compact_value(state.verification_conflicts)}
    return {**common, "status": state.status.value, "tasks": [task.model_dump(mode="json") for task in state.tasks]}


def build_agent_messages(agent_name: str, state: AgentState, system_prompt: str) -> list[dict[str, Any]]:
    """Build the initial provider conversation for one agent turn."""

    context = build_agent_context(agent_name, state)
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(context, ensure_ascii=False, separators=(",", ":"), default=str),
        },
    ]


def append_assistant_tool_calls(
    messages: list[dict[str, Any]],
    *,
    content: str | None,
    tool_calls: list[dict[str, Any]],
) -> None:
    """Append the provider assistant tool-call message in OpenAI shape."""

    if not tool_calls:
        return
    messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})


def append_tool_result(
    messages: list[dict[str, Any]],
    *,
    tool_call_id: str,
    output: dict[str, Any],
) -> None:
    """Append a matching OpenAI ``role=tool`` result message."""

    messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(output, ensure_ascii=False, separators=(",", ":"), default=str),
        }
    )
