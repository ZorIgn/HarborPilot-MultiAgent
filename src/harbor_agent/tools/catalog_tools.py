from __future__ import annotations

from pydantic import BaseModel, Field

from harbor_agent.services.deterministic_catalog import get_program_detail, search_program_catalog
from harbor_agent.models import NormalizedProfile, Program
from harbor_agent.runtime.state import AgentState
from harbor_agent.services.data_loader import load_programs
from harbor_agent.tools.base import EmptyToolInput, ToolDefinition


class ProgramIdInput(BaseModel):
    program_id: str


class CatalogSearchResult(BaseModel):
    programs: list[dict] = Field(default_factory=list)
    program_ids: list[str] = Field(default_factory=list)


class ProgramDetailResult(BaseModel):
    program: dict | None = None


def _search(state: AgentState, _: EmptyToolInput) -> CatalogSearchResult:
    if state.normalized_profile is None:
        raise ValueError("normalized profile is required")
    profile = NormalizedProfile.model_validate(state.normalized_profile)
    programs = search_program_catalog(profile)

    # A student's explicit selection must be evaluated even when it falls
    # outside the catalogue's ranked recall set. Matching still applies all
    # hard rules; this only prevents the selection from disappearing first.
    seen_ids = {item.id for item in programs}
    by_id = {item.id: item for item in load_programs()}
    for program_id in state.selected_program_ids:
        item = by_id.get(program_id)
        if (
            item is None
            or item.id in seen_ids
            or item.cycle != profile.target_cycle
            or item.country not in profile.target_regions
            or item.degree_type != "taught_master"
        ):
            continue
        programs.append(item)
        seen_ids.add(item.id)

    return CatalogSearchResult(
        programs=[item.model_dump(mode="json") for item in programs],
        program_ids=[item.id for item in programs],
    )


def _detail(_: AgentState, args: ProgramIdInput) -> ProgramDetailResult:
    item = get_program_detail(args.program_id)
    return ProgramDetailResult(program=item.model_dump(mode="json") if item else None)


def _related(state: AgentState, _: EmptyToolInput) -> CatalogSearchResult:
    result = _search(state, EmptyToolInput())
    profile = NormalizedProfile.model_validate(state.normalized_profile or {})
    tags = set(profile.discipline_tags)
    related = [item for item in result.programs if tags & set(item.get("discipline_tags", []))]
    return CatalogSearchResult(programs=related[:40], program_ids=[str(item["id"]) for item in related[:40]])


def definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition("search_program_catalog", "Search the deterministic programme catalogue for the normalized applicant profile.", EmptyToolInput, CatalogSearchResult, _search),
        ToolDefinition("get_program_detail", "Load one programme's structured catalogue record.", ProgramIdInput, ProgramDetailResult, _detail),
        ToolDefinition("search_related_programs", "Find related catalogue programmes without inventing programme facts.", EmptyToolInput, CatalogSearchResult, _related),
    ]
