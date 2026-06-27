from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from harbor_agent.agents.profile import ProfileAgent
from harbor_agent.core.rules import check_program_eligibility, hard_rules_pass, normalized_gpa_100
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
    assert normalized_gpa_100(3.7, "4.0") == 92.5
    assert normalized_gpa_100(4.3, "5.0") == 86.0
    assert normalized_gpa_100(86, "100") == 86
