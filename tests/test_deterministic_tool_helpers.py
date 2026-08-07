from __future__ import annotations

import ast
import json
from datetime import date
from pathlib import Path

from harbor_agent.core.llm import MockLLMProvider
from harbor_agent.services.assessment_explanation_service import AssessmentExplanationService
from harbor_agent.services.matching_heuristics import MatchingHeuristicService
from harbor_agent.models import ApplicantProfileInput, ProgramMatch, QuestionnaireAnswer, QuestionnaireResponse, WritingDraft
from harbor_agent.services.data_loader import load_programs
from harbor_agent.services.deterministic_assessment import calculate_profile_assessment
from harbor_agent.services.deterministic_catalog import search_program_catalog
from harbor_agent.services.deterministic_matching import calculate_applicant_fit
from harbor_agent.services.deterministic_profile import inspect_evidence_readiness, normalize_profile
from harbor_agent.services.deterministic_review import run_review_gate
from harbor_agent.services.deterministic_timeline import build_timeline_tasks
from harbor_agent.services.deterministic_writing import build_story_cards


def _profile() -> ApplicantProfileInput:
    return ApplicantProfileInput.model_validate(
        json.loads(Path("examples/sample_profile.json").read_text(encoding="utf-8"))
    )


def test_profile_and_evidence_helpers_match_compatibility_implementations() -> None:
    payload = _profile()
    legacy_profile = normalize_profile(payload)
    helper_profile = normalize_profile(payload)

    assert helper_profile.model_dump(mode="json") == legacy_profile.model_dump(mode="json")
    assert inspect_evidence_readiness(helper_profile).model_dump(mode="json") == inspect_evidence_readiness(
        legacy_profile
    ).model_dump(mode="json")


def test_assessment_catalog_and_matching_helpers_match_mock_compatibility_paths() -> None:
    profile = normalize_profile(_profile())
    assessment = calculate_profile_assessment(profile)
    assert assessment.model_dump(mode="json") == AssessmentExplanationService(MockLLMProvider()).run(profile).model_dump(mode="json")

    helper_catalog = search_program_catalog(profile)
    compatibility_catalog = search_program_catalog(profile)
    assert [item.model_dump(mode="json") for item in helper_catalog] == [
        item.model_dump(mode="json") for item in compatibility_catalog
    ]

    scoring_profile = profile.model_copy(update={"budget_hkd": None})
    programs = helper_catalog[:15]
    helper_matches = calculate_applicant_fit(scoring_profile, assessment, programs, pinned_program_ids=[])
    compatibility_matches = MatchingHeuristicService(MockLLMProvider()).run(
        scoring_profile, assessment, programs, pinned_program_ids=[]
    )
    assert [item.model_dump(mode="json") for item in helper_matches] == [
        item.model_dump(mode="json") for item in compatibility_matches
    ]

def test_story_card_helper_matches_compatibility_implementation() -> None:
    questionnaire = QuestionnaireResponse(
        profile_answers=[
            QuestionnaireAnswer(field_id="academic_strength", value="统计课程完成了一个数据项目", evidence_ids=["e1"]),
            QuestionnaireAnswer(field_id="gpa_rank", value="3.7/4.0", evidence_ids=["e2"]),
        ],
        statement_answers=[
            QuestionnaireAnswer(field_id="practice_problem", value="优化报表延迟", evidence_ids=["e3"]),
            QuestionnaireAnswer(field_id="practice_actions", value="Python SQL 建模", evidence_ids=["e4"]),
            QuestionnaireAnswer(field_id="practice_result", value="延迟下降 30%", evidence_ids=["e5"]),
        ],
    )

    assert [item.model_dump() for item in build_story_cards(questionnaire)] == [
        item.model_dump() for item in build_story_cards(questionnaire)
    ]


def test_timeline_and_review_helpers_match_compatibility_implementations() -> None:
    programs = [item for item in load_programs() if item.application_url][:3]
    matches = [
        ProgramMatch(
            program=program,
            tier="target",
            fit_score=72,
            hard_rule_passed=True,
            reasons=["student selected this program"],
            risks=[],
            actions=[],
            rule_checks=[],
        )
        for program in programs
    ]

    assert [item.model_dump(mode="json") for item in build_timeline_tasks(matches, today=date(2026, 7, 5))] == [
        item.model_dump(mode="json") for item in build_timeline_tasks(matches, today=date(2026, 7, 5))
    ]
    draft = WritingDraft.model_construct(fact_bindings=[], review_flags=[])
    assert not run_review_gate(matches, draft).get("passed")


def test_runtime_tool_modules_do_not_depend_on_legacy_agent_classes() -> None:
    tool_files = [
        Path("src/harbor_agent/tools/profile_tools.py"),
        Path("src/harbor_agent/tools/planning_tools.py"),
        Path("src/harbor_agent/tools/writing_tools.py"),
        Path("src/harbor_agent/tools/review_tools.py"),
        Path("src/harbor_agent/tools/assessment_tools.py"),
        Path("src/harbor_agent/tools/catalog_tools.py"),
        Path("src/harbor_agent/tools/matching_tools.py"),
    ]
    legacy_names = {"ProfileAgent", "EvidenceAgent", "TimelineAgent", "StoryCardAgent", "ReviewAgent", "EvaluationAgent", "ProgramIntelligenceAgent", "SchoolMatchingAgent"}

    for path in tool_files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        used_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert not (legacy_names & imported_names), path
        assert not (legacy_names & used_names), path
