from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from harbor_agent.services.deterministic_timeline import build_timeline_tasks
from harbor_agent.models import ProgramMatch, TimelineTask
from harbor_agent.runtime.state import AgentState
from harbor_agent.services.formal_gate import formal_timeline_blockers, formal_timeline_ready
from harbor_agent.tools.base import EmptyToolInput, ToolDefinition


class TimelineReadinessResult(BaseModel):
    ready: bool
    blockers: dict[str, list[str]] = Field(default_factory=dict)


class TimelineResult(BaseModel):
    tasks: list[dict] = Field(default_factory=list)
    formal: bool = False


def _matches(state: AgentState) -> list[ProgramMatch]:
    candidates = state.selected_matches or list(state.program_matches.values())
    return [ProgramMatch.model_validate(item) for item in candidates]


def _readiness(state: AgentState, _: EmptyToolInput) -> TimelineReadinessResult:
    matches = _matches(state)
    blockers = {item.program.id: formal_timeline_blockers(item) for item in matches if not formal_timeline_ready(item)}
    return TimelineReadinessResult(ready=bool(matches) and not blockers, blockers=blockers)


def _preparation(state: AgentState, _: EmptyToolInput) -> TimelineResult:
    tasks = build_timeline_tasks(_matches(state), today=date.today())
    return TimelineResult(tasks=[item.model_dump(mode="json") for item in tasks], formal=False)


def _official(state: AgentState, _: EmptyToolInput) -> TimelineResult:
    eligible = [item for item in _matches(state) if formal_timeline_ready(item)]
    tasks = build_timeline_tasks(eligible, today=date.today()) if eligible else []
    return TimelineResult(tasks=[item.model_dump(mode="json") for item in tasks], formal=True)


def _merge(state: AgentState, _: EmptyToolInput) -> TimelineResult:
    seen: set[tuple[str, str]] = set()
    merged: list[dict] = []
    for task in state.timeline:
        key = (str(task.get("title", "")), str(task.get("due_date", "")))
        if key not in seen:
            merged.append(task)
            seen.add(key)
    return TimelineResult(tasks=merged, formal=state.timeline_ready)


def definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition("inspect_timeline_readiness", "Check whether official current-cycle fields permit a formal timeline.", EmptyToolInput, TimelineReadinessResult, _readiness),
        ToolDefinition("build_preparation_timeline", "Build non-formal preparation tasks without asserting unverified deadlines.", EmptyToolInput, TimelineResult, _preparation),
        ToolDefinition("build_official_timeline", "Build a formal timeline only for programmes that pass the official-field gate.", EmptyToolInput, TimelineResult, _official),
        ToolDefinition("merge_shared_tasks", "Deduplicate shared preparation tasks deterministically.", EmptyToolInput, TimelineResult, _merge),
    ]
