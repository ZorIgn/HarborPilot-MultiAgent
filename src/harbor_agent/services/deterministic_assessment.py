"""Deterministic applicant assessment used by AssessmentAgent tools."""

from __future__ import annotations

from harbor_agent.core.rules import evaluate_general_profile
from harbor_agent.models import AssessmentResult, NormalizedProfile


def calculate_profile_assessment(profile: NormalizedProfile) -> AssessmentResult:
    """Calculate typed academic, language, experience and readiness scores."""

    return evaluate_general_profile(profile)
