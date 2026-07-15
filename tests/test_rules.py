from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from harbor_agent.agents.profile import ProfileAgent
from harbor_agent.core.rules import check_program_eligibility, evaluate_general_profile, hard_rules_pass, normalized_gpa_100
from harbor_agent.models import ApplicantProfileInput
from harbor_agent.services.data_loader import load_programs


def test_hard_rule_fails_when_language_is_missing() -> None:
    payload = ApplicantProfileInput.model_validate_json(
        Path("examples/sample_profile.json").read_text(encoding="utf-8")
    )
    payload = deepcopy(payload)
    payload.language.test = "NONE"
    payload.language.overall = None

    profile = ProfileAgent().run(payload)
    program = next(item for item in load_programs() if item.id == "nus-master-of-computing-2027")
    checks = check_program_eligibility(profile, program)

    assert not hard_rules_pass(checks)
    assert any(check.rule_id == "language_required" and not check.passed for check in checks)


def test_toefl_is_not_reported_as_ielts() -> None:
    payload = ApplicantProfileInput.model_validate_json(
        Path("examples/sample_profile.json").read_text(encoding="utf-8")
    )
    payload = deepcopy(payload)
    payload.language.test = "TOEFL"
    payload.language.overall = 90

    profile = ProfileAgent().run(payload)
    program = next(item for item in load_programs() if item.id == "nus-master-of-computing-2027")
    checks = check_program_eligibility(profile, program)

    messages = " ".join(check.message for check in checks)
    assert "IELTS 90" not in messages
    assert any(check.rule_id in {"toefl_overall", "language_test_mismatch"} for check in checks)


def test_gpa_scale_is_normalized_before_rules() -> None:
    assert normalized_gpa_100(3.7, "4.0") == 90.0
    assert normalized_gpa_100(4.3, "5.0") == 86.0
    assert normalized_gpa_100(86, "100") == 86


def test_chinese_core_courses_satisfy_programming_and_statistics_prerequisites() -> None:
    payload = ApplicantProfileInput.model_validate_json(
        Path("examples/sample_profile.json").read_text(encoding="utf-8")
    )
    payload = deepcopy(payload)
    payload.raw_interest_text = ""
    payload.additional_background.core_courses = ["Python 程序设计", "概率论与数理统计", "数据库系统"]

    profile = ProfileAgent().run(payload)
    program = next(item for item in load_programs() if item.id == "cityu-msc-business-information-systems-2027")
    prerequisite = next(check for check in check_program_eligibility(profile, program) if check.rule_id == "prerequisite_signal")

    assert prerequisite.passed is True
    assert "缺少先修课" not in prerequisite.message

def test_structured_core_courses_survive_profile_normalization_and_assessment() -> None:
    payload = ApplicantProfileInput.model_validate_json(
        Path("examples/sample_profile.json").read_text(encoding="utf-8")
    )
    payload = deepcopy(payload)
    payload.raw_interest_text = ""
    payload.additional_background.core_courses = ["Linear Algebra 91", "Database Systems 88", "Statistics 90"]
    payload.additional_background.skills = ["Python", "SQL"]

    profile = ProfileAgent().run(payload)
    assessment = evaluate_general_profile(profile)
    course_finding = assessment.dimension_findings[1]

    assert profile.additional_background.core_courses == ["Linear Algebra 91", "Database Systems 88", "Statistics 90"]
    assert "Database Systems" in profile.raw_interest_text
    assert course_finding.level != "\u4fe1\u606f\u4e0d\u8db3"
    assert not any("6-10" in action for action in assessment.strengthening_actions)


def test_required_computing_background_blocks_unrelated_major_without_evidence() -> None:
    payload = ApplicantProfileInput.model_validate_json(
        Path("examples/sample_profile.json").read_text(encoding="utf-8")
    )
    payload = deepcopy(payload)
    payload.education.major = "Business Administration"
    payload.discipline_interests = ["business"]
    payload.raw_interest_text = ""
    payload.career_goal = "Brand and market operations"
    payload.additional_background.core_courses = []
    payload.additional_background.skills = []
    payload.additional_background.research_outputs = []
    payload.additional_background.activities = []
    payload.additional_background.awards = []
    payload.experiences = []

    profile = ProfileAgent().run(payload)
    program = next(item for item in load_programs() if item.id == "hku-master-of-science-in-computer-science-2027")
    checks = check_program_eligibility(profile, program)
    background = next(check for check in checks if check.rule_id == "required_background")

    assert background.severity == "hard"
    assert background.passed is False
    assert not hard_rules_pass(checks)
    assert "\u8ba1\u7b97\u673a/\u7f16\u7a0b\u80cc\u666f" in background.message


def test_required_computing_background_can_be_met_by_structured_courses() -> None:
    payload = ApplicantProfileInput.model_validate_json(
        Path("examples/sample_profile.json").read_text(encoding="utf-8")
    )
    payload = deepcopy(payload)
    payload.education.major = "Business Administration"
    payload.discipline_interests = ["business"]
    payload.raw_interest_text = ""
    payload.additional_background.core_courses = ["Python Programming 92", "Database Systems 88", "Data Structures 90"]
    payload.additional_background.skills = ["SQL", "Python"]
    payload.experiences = []

    profile = ProfileAgent().run(payload)
    program = next(item for item in load_programs() if item.id == "hku-master-of-science-in-computer-science-2027")
    checks = check_program_eligibility(profile, program)
    background = next(check for check in checks if check.rule_id == "required_background")

    assert background.passed is True
    assert "\u4e13\u4e1a\u80cc\u666f\u8981\u6c42" in background.message


def test_sparse_profile_returns_needs_data_instead_of_competitiveness_grade() -> None:
    payload = ApplicantProfileInput.model_validate_json(Path("examples/sample_profile.json").read_text(encoding="utf-8"))
    payload = deepcopy(payload)
    payload.education.major = ""
    payload.education.gpa = 0
    payload.education.school_tier = "unknown"
    payload.discipline_interests = []
    payload.raw_interest_text = ""
    payload.career_goal = ""
    payload.experiences = []
    payload.additional_background.core_courses = []
    payload.additional_background.skills = []

    assessment = evaluate_general_profile(ProfileAgent().run(payload))

    assert assessment.overall_level == "NEEDS_DATA"
    assert assessment.confidence == "low"
    assert "不足" in assessment.competitiveness_summary


def test_ai_intention_alone_does_not_satisfy_computing_background() -> None:
    payload = ApplicantProfileInput.model_validate_json(Path("examples/sample_profile.json").read_text(encoding="utf-8"))
    payload = deepcopy(payload)
    payload.education.major = "Business Administration"
    payload.discipline_interests = ["artificial_intelligence"]
    payload.raw_interest_text = "AI machine learning computer science"
    payload.career_goal = "AI product manager"
    payload.additional_background.core_courses = []
    payload.additional_background.skills = []
    payload.additional_background.research_outputs = []
    payload.experiences = []

    program = next(item for item in load_programs() if item.id == "hku-master-of-science-in-computer-science-2027")
    checks = check_program_eligibility(ProfileAgent().run(payload), program)
    background = next(check for check in checks if check.rule_id == "required_background")

    assert background.passed is False


def test_tuition_above_budget_is_a_hard_rule_failure() -> None:
    payload = ApplicantProfileInput.model_validate_json(Path("examples/sample_profile.json").read_text(encoding="utf-8"))
    payload = deepcopy(payload)
    payload.budget_hkd = 200000
    program = next(item for item in load_programs() if item.id == "smu-master-of-it-in-business-2027")

    checks = check_program_eligibility(ProfileAgent().run(payload), program)
    budget = next(check for check in checks if check.rule_id == "tuition_budget")

    assert budget.severity == "hard"
    assert budget.passed is False
    assert not hard_rules_pass(checks)


def test_low_language_score_is_reported_as_priority_blocker() -> None:
    payload = ApplicantProfileInput.model_validate_json(Path("examples/sample_profile.json").read_text(encoding="utf-8"))
    payload = deepcopy(payload)
    payload.language.test = "IELTS"
    payload.language.overall = 5.5

    assessment = evaluate_general_profile(ProfileAgent().run(payload))

    assert "低于" in assessment.qualification_status
    assert "重考" in assessment.qualification_status
