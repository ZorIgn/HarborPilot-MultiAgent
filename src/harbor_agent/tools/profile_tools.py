from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from harbor_agent.models import ApplicantProfileInput, EvidenceReview, NormalizedProfile
from harbor_agent.runtime.state import AgentState
from harbor_agent.services.deterministic_profile import inspect_evidence_readiness, normalize_profile
from harbor_agent.tools.base import EmptyToolInput, ToolDefinition


class ProfileGapResult(BaseModel):
    missing_fields: list[str] = Field(default_factory=list)
    critical_missing_fields: list[str] = Field(default_factory=list)


def _profile(state: AgentState, _: EmptyToolInput) -> NormalizedProfile:
    if state.raw_profile is None:
        raise ValueError("raw_profile is required")
    return normalize_profile(ApplicantProfileInput.model_validate(state.raw_profile))


def _gaps(state: AgentState, _: EmptyToolInput) -> ProfileGapResult:
    if state.normalized_profile is None:
        raw = state.raw_profile or {}
        education = raw.get("education") if isinstance(raw.get("education"), dict) else {}
        missing: list[str] = []
        if not education:
            missing.append("教育背景")
        if not isinstance(education.get("major"), str) or not education["major"].strip():
            missing.append("教育背景：本科专业")
        gpa = education.get("gpa")
        if isinstance(gpa, bool) or gpa is None or (isinstance(gpa, str) and not gpa.strip()):
            missing.append("GPA")

        # Surface malformed raw fields as a resumable user request rather
        # than turning the first normalization attempt into a failed workflow.
        if not missing:
            try:
                ApplicantProfileInput.model_validate(raw)
            except ValidationError as exc:
                for error in exc.errors():
                    location = ".".join(str(item) for item in error.get("loc", ()))
                    label = {
                        "education.gpa": "GPA",
                        "education.major": "教育背景：本科专业",
                        "target_cycle": "申请季",
                        "target_regions": "申请地区",
                    }.get(location, location or "档案字段")
                    if label:
                        missing.append(label)
        missing = list(dict.fromkeys(missing))
        return ProfileGapResult(missing_fields=missing, critical_missing_fields=missing)
    profile = NormalizedProfile.model_validate(state.normalized_profile)
    critical_markers = ("教育", "GPA", "语言", "目标", "专业")
    missing = list(profile.missing_fields)
    return ProfileGapResult(
        missing_fields=missing,
        critical_missing_fields=[item for item in missing if any(marker in item for marker in critical_markers)],
    )


def _evidence(state: AgentState, _: EmptyToolInput) -> EvidenceReview:
    if state.normalized_profile is None:
        raise ValueError("normalize_profile must run first")
    return inspect_evidence_readiness(NormalizedProfile.model_validate(state.normalized_profile))


def definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition("normalize_profile", "Normalize the submitted applicant profile with deterministic taxonomy rules.", EmptyToolInput, NormalizedProfile, _profile),
        ToolDefinition("find_profile_gaps", "Find required and high-priority missing applicant fields.", EmptyToolInput, ProfileGapResult, _gaps),
        ToolDefinition("inspect_profile_gaps", "Inspect profile completeness and required field gaps.", EmptyToolInput, ProfileGapResult, _gaps),
        ToolDefinition("inspect_evidence_readiness", "Assess self-reported facts and evidence readiness.", EmptyToolInput, EvidenceReview, _evidence),
    ]
