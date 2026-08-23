from __future__ import annotations

from copy import deepcopy

from harbor_agent.agents.research import ResearchAgent
from harbor_agent.models import SourceRegistry
from harbor_agent.runtime.decision import DecisionType
from harbor_agent.runtime.state import AgentState, WorkflowGoal
from harbor_agent.services.data_loader import load_programs, load_source_registry
from harbor_agent.services.source_research import (
    SourceResearchLimits,
    SourceResearchPlan,
    build_source_research_plan,
)


def test_source_research_plan_contains_only_allowlisted_official_sources() -> None:
    programs = load_programs()[:4]
    plan = build_source_research_plan(
        [program.id for program in programs],
        programs=programs,
        registry=load_source_registry(),
    )

    assert plan.targets
    assert plan.publication_allowed is False
    assert plan.network_allowed is False
    assert all(source.trust_level == "official" for target in plan.targets for source in target.sources)
    assert all(source.url.startswith("https://") for target in plan.targets for source in target.sources)
    assert all(source.official_domain in target.allowed_domains for target in plan.targets for source in target.sources)
    assert all(source.scope in {"institution_index", "programme_detail", "application_portal"} for target in plan.targets for source in target.sources)
    assert all("community" not in source.url.lower() for target in plan.targets for source in target.sources)
    assert all("github" not in source.url.lower() for target in plan.targets for source in target.sources)


def test_source_research_plan_enforces_per_program_and_global_stopping_limits() -> None:
    programs = load_programs()[:8]
    limits = SourceResearchLimits(
        max_programs=3,
        max_urls_per_program=2,
        max_total_urls=4,
        max_fields_per_program=4,
        max_registry_sources_per_program=1,
    )
    plan = build_source_research_plan(
        [program.id for program in programs],
        programs=programs,
        registry=load_source_registry(),
        limits=limits,
    )

    assert len(plan.candidate_program_ids) <= limits.max_programs
    assert len(plan.targets) <= limits.max_programs
    assert plan.total_url_count <= limits.max_total_urls
    assert all(len(target.sources) <= limits.max_urls_per_program for target in plan.targets)
    assert all(len(target.field_targets) <= limits.max_fields_per_program for target in plan.targets)
    assert plan.stop_conditions
    assert any("max_total_urls" in item for item in plan.stop_conditions)
    assert any("max_programs" in item for item in plan.stop_conditions)


def test_unknown_or_unallowlisted_candidates_never_become_open_web_sources() -> None:
    programs = load_programs()[:1]
    plan = build_source_research_plan(
        ["does-not-exist", programs[0].id],
        programs=programs,
        registry=load_source_registry(),
    )

    assert plan.candidate_program_ids == [programs[0].id]
    assert any("unknown catalogue programme" in warning for warning in plan.warnings)
    assert all(source.official_domain for target in plan.targets for source in target.sources)


def test_research_agent_builds_and_stores_plan_before_supervisor_handoff() -> None:
    state = AgentState(
        workflow_id="source-research-plan",
        goal=WorkflowGoal.PROGRAM_RECOMMENDATION,
        raw_profile={},
        normalized_profile={},
        working_memory={
            "tool_results": {
                "search_program_catalog": {
                    "program_ids": ["program-a"],
                    "programs": [{"id": "program-a"}],
                }
            }
        },
    )

    first = ResearchAgent().step(state)
    assert first.decision == DecisionType.CALL_TOOL
    assert [call.tool_name for call in first.tool_calls] == ["build_source_research_plan"]

    plan = {
        "plan_version": "source-research-v1",
        "candidate_program_ids": ["program-a"],
        "targets": [],
        "limits": SourceResearchLimits().model_dump(mode="json"),
        "total_url_count": 0,
        "publication_allowed": False,
        "network_allowed": False,
        "stop_conditions": ["bounded"],
        "warnings": ["no allowlisted official source known for programme: program-a"],
    }
    state_with_plan = state.model_copy(deep=True)
    state_with_plan.working_memory["tool_results"]["build_source_research_plan"] = plan
    second = ResearchAgent().step(state_with_plan)

    assert second.decision == DecisionType.HANDOFF
    assert second.next_agent == "SupervisorAgent"
    assert second.state_patch["working_memory"]["source_research_plan"] == plan
    assert second.state_patch["working_memory"]["source_research_plan"]["publication_allowed"] is False


def test_plan_is_not_a_verified_fact_or_catalog_mutation() -> None:
    programs = load_programs()[:1]
    before = deepcopy(programs[0].model_dump(mode="json"))
    plan = build_source_research_plan(
        [programs[0].id],
        programs=programs,
        registry=SourceRegistry.model_validate(load_source_registry().model_dump(mode="json")),
    )

    assert SourceResearchPlan.model_validate(plan.model_dump(mode="json")).publication_allowed is False
    assert not any(source.scope == "published" for target in plan.targets for source in target.sources)
    assert programs[0].model_dump(mode="json") == before
