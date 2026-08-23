"""Canonical, evidence-backed programme facts for every hard decision.

The catalogue deliberately remains useful for discovery and rendering.  It is
not a source of formal admissions, cost, deadline or writing facts.  This
module is the one place where candidate evidence becomes a read-only decision
view, so matching, planning, writing and Critic do not each reinterpret a
mixture of seed values and evidence records.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from harbor_agent.models import (
    DecisionFact,
    DecisionStatus,
    FactProvenanceStatus,
    FieldEvidenceRecord,
    FieldVerificationStatus,
    Program,
    ProgramRequirement,
    ResolvedProgramView,
    SourceScope,
)
from harbor_agent.services.program_store import load_field_evidence_records
from harbor_agent.services.field_contract import (
    FORMAL_RECOMMENDATION_FIELDS,
    HARD_ADMISSIONS_FIELDS,
)


# A field can only be used formally when its source was reviewed in a scope
# capable of proving that particular fact.  An institution index may discover a
# programme, but is intentionally never sufficient for its tuition or deadline.
FORMAL_SCOPE_BY_FIELD: dict[str, set[SourceScope]] = {
    "institution": {SourceScope.institution_index, SourceScope.programme_detail},
    "program_name": {SourceScope.institution_index, SourceScope.programme_detail},
    "official_program_url": {SourceScope.programme_detail},
    "application_url": {SourceScope.programme_detail, SourceScope.application_portal},
    "deadline": {SourceScope.programme_detail, SourceScope.application_portal},
    "application_rounds": {SourceScope.programme_detail, SourceScope.application_portal},
    "tuition_hkd": {SourceScope.programme_detail, SourceScope.application_portal},
    "application_fee_hkd": {SourceScope.programme_detail, SourceScope.application_portal},
    "min_gpa": {SourceScope.programme_detail, SourceScope.application_portal},
    "language_requirement": {SourceScope.programme_detail, SourceScope.application_portal},
    "required_backgrounds": {SourceScope.programme_detail, SourceScope.application_portal},
    "preferred_backgrounds": {SourceScope.programme_detail, SourceScope.application_portal},
    "prerequisites": {SourceScope.programme_detail, SourceScope.application_portal},
    "portfolio_required": {SourceScope.programme_detail, SourceScope.application_portal},
    "work_experience_preferred": {SourceScope.programme_detail, SourceScope.application_portal},
    "materials": {SourceScope.programme_detail, SourceScope.application_portal},
    "essay_prompts": {SourceScope.programme_detail, SourceScope.application_portal},
}

def resolve_program_view(
    program: Program,
    *,
    evidence_records: Iterable[FieldEvidenceRecord] | None = None,
    cycle: str | None = None,
) -> ResolvedProgramView:
    """Project a programme's reviewed evidence into one canonical read model.

    Passing ``evidence_records`` is intentionally supported for isolated tests,
    offline import previews and batch resolution.  The production default reads
    the SQLite candidate/evidence store only; it never treats
    ``Program.field_evidence`` or synthetic seed records as published truth.
    """

    target_cycle = cycle or program.cycle
    records = list(evidence_records) if evidence_records is not None else load_field_evidence_records([program.id])
    relevant = [record for record in records if record.program_id == program.id]
    field_names = set(FORMAL_SCOPE_BY_FIELD) | {record.field_name for record in relevant}
    facts: dict[str, DecisionFact] = {}
    conflict_ids: list[str] = []

    for field_name in sorted(field_names):
        fact = _resolve_field(program, field_name, target_cycle, relevant)
        facts[field_name] = fact
        if fact.conflict_id:
            conflict_ids.append(fact.conflict_id)

    blockers: list[str] = []
    for field_name in FORMAL_RECOMMENDATION_FIELDS:
        fact = facts[field_name]
        # ``decision_status`` and ``formal_use_ready`` are intentionally both
        # required here.  A caller can construct a compatibility view with a
        # PASS fact, but without the provenance flag; that view must not be
        # allowed to masquerade as a fully resolved programme.
        if (
            fact.decision_status == DecisionStatus.PASS
            and fact.formal_use_ready
            and fact.normalized_value is not None
        ):
            continue
        blockers.append(
            f"{field_name}: {fact.blockers[0] if fact.blockers else '字段没有可用于正式决策的当前周期事实。'}"
        )
    readiness = DecisionStatus.PASS if not blockers else DecisionStatus.UNKNOWN
    summary = Counter(fact.provenance_status.value for fact in facts.values())
    summary["FORMAL_FACTS"] = sum(
        fact.formal_use_ready for fact in facts.values()
    )
    return ResolvedProgramView(
        program_id=program.id,
        cycle=target_cycle,
        catalog=program,
        facts=facts,
        conflict_ids=sorted(set(conflict_ids)),
        formal_readiness=readiness,
        formal_blockers=blockers,
        provenance_summary=dict(summary),
    )


def resolve_program_views(
    programs: Iterable[Program],
    *,
    evidence_records: Iterable[FieldEvidenceRecord] | None = None,
    cycle: str | None = None,
) -> dict[str, ResolvedProgramView]:
    """Resolve a batch with one evidence-store read, avoiding N+1 lookups."""

    program_list = list(programs)
    if evidence_records is None:
        evidence_records = load_field_evidence_records([program.id for program in program_list])
    by_program: dict[str, list[FieldEvidenceRecord]] = defaultdict(list)
    for record in evidence_records:
        by_program[record.program_id].append(record)
    return {
        program.id: resolve_program_view(
            program,
            evidence_records=by_program.get(program.id, []),
            cycle=cycle,
        )
        for program in program_list
    }


def decision_fact_value(view: ResolvedProgramView, field_name: str) -> Any | None:
    """Return a value only when it is formally usable for the selected cycle."""

    fact = view.fact(field_name)
    return fact.normalized_value if fact.formal_use_ready else None


def formal_fact(view: ResolvedProgramView, field_name: str) -> DecisionFact:
    """Small semantic helper used by rule, timeline and writing consumers."""

    return view.fact(field_name)


def materialize_decision_program(view: ResolvedProgramView) -> Program:
    """Return a compatibility ``Program`` whose hard fields come only from facts.

    Several mature scoring helpers still accept ``Program``.  This adapter
    keeps their public signature stable while ensuring that an unverified seed
    value is replaced by ``None``/an empty requirement before it can affect a
    predicate, budget cap or official-facing explanation.
    """

    catalog = view.catalog
    requirements = catalog.requirements.model_copy(
        update={
            "min_gpa": decision_fact_value(view, "min_gpa"),
            "language": decision_fact_value(view, "language_requirement") or {},
            "required_backgrounds": decision_fact_value(view, "required_backgrounds") or [],
            "preferred_backgrounds": decision_fact_value(view, "preferred_backgrounds") or [],
            "prerequisites": decision_fact_value(view, "prerequisites") or [],
            "portfolio_required": bool(decision_fact_value(view, "portfolio_required")),
            "work_experience_preferred": bool(
                decision_fact_value(view, "work_experience_preferred")
            ),
        }
    )
    deadline = decision_fact_value(view, "deadline") or "NOT_PUBLISHED"
    return catalog.model_copy(
        update={
            "requirements": ProgramRequirement.model_validate(requirements),
            "tuition_hkd": decision_fact_value(view, "tuition_hkd"),
            "application_fee_hkd": decision_fact_value(view, "application_fee_hkd"),
            "deadline": deadline,
            "application_url": decision_fact_value(view, "application_url"),
            "official_program_url": decision_fact_value(view, "official_program_url"),
            "materials": decision_fact_value(view, "materials") or [],
            # ``VERIFIED`` is not inherited from a whole catalogue row.  It is
            # only a compatibility display hint for fully resolved facts.
            "data_status": "VERIFIED"
            if view.formal_readiness == DecisionStatus.PASS
            else "PENDING_REVIEW",
            "last_verified_at": max(
                (
                    fact.verified_at
                    for fact in view.facts.values()
                    if fact.formal_use_ready and fact.verified_at is not None
                ),
                default=None,
            ),
        }
    )


def _resolve_field(
    program: Program,
    field_name: str,
    target_cycle: str,
    records: list[FieldEvidenceRecord],
) -> DecisionFact:
    catalog_value = _catalog_value(program, field_name)
    candidates = [record for record in records if record.field_name == field_name]
    eligible: list[tuple[FieldEvidenceRecord, Any]] = []
    candidate_blockers: list[str] = []
    for record in candidates:
        blockers = _formal_record_blockers(record, field_name, target_cycle)
        normalized = normalize_field_value(field_name, record.value)
        if normalized is None and record.value not in {None, "", "NOT_PUBLISHED"}:
            blockers.append("字段值不能按该字段类型确定性规范化。")
        if not blockers and normalized is not None:
            eligible.append((record, normalized))
        else:
            candidate_blockers.extend(blockers)

    if eligible:
        values = {_canonical_value(value) for _, value in eligible}
        if len(values) > 1:
            conflict_id = _conflict_id(program.id, target_cycle, field_name, values)
            return DecisionFact(
                fact_id=f"conflict:{conflict_id}",
                program_id=program.id,
                field_name=field_name,
                cycle=target_cycle,
                catalog_value=catalog_value,
                decision_status=DecisionStatus.UNKNOWN,
                provenance_status=FactProvenanceStatus.CONFLICTED,
                conflict_id=conflict_id,
                blockers=["当前周期的已发布来源对该字段给出了不一致值；必须人工裁决。"],
            )
        record, normalized = sorted(eligible, key=_record_sort_key)[0]
        return DecisionFact(
            fact_id=_fact_id(program.id, target_cycle, field_name, record.evidence_id),
            program_id=program.id,
            field_name=field_name,
            cycle=target_cycle,
            catalog_value=catalog_value,
            raw_value=record.value,
            normalized_value=normalized,
            decision_status=DecisionStatus.PASS,
            provenance_status=FactProvenanceStatus.VERIFIED_CURRENT,
            formal_use_ready=True,
            evidence_id=record.evidence_id,
            source_url=record.source_url,
            source_scope=record.source_scope,
            source_type=record.source_type,
            source_locator=record.page_title,
            evidence_quote=record.evidence_snippet,
            snapshot_url=record.snapshot_url,
            page_hash=record.page_hash,
            observed_at=record.extracted_at,
            verified_at=record.verified_at,
            reviewer_id=record.reviewer_id,
            review_decision_id=record.review_decision_id,
        )

    provenance, derived_blockers = _unusable_provenance(candidates, target_cycle)
    blockers = _stable_unique([*derived_blockers, *candidate_blockers])
    if not blockers:
        blockers = ["该字段只有 catalog seed 或尚未采集的候选值，不能用于正式决策。"]
    return DecisionFact(
        fact_id=_fact_id(program.id, target_cycle, field_name, None),
        program_id=program.id,
        field_name=field_name,
        cycle=target_cycle,
        catalog_value=catalog_value,
        decision_status=DecisionStatus.UNKNOWN,
        provenance_status=provenance,
        formal_use_ready=False,
        blockers=blockers,
    )


def _formal_record_blockers(
    record: FieldEvidenceRecord,
    field_name: str,
    target_cycle: str,
) -> list[str]:
    blockers: list[str] = []
    if record.status != FieldVerificationStatus.official_verified_current:
        blockers.append("证据不是当前申请季的已审核官方字段。")
    if record.review_required:
        blockers.append("字段仍处于待审核状态。")
    if not _cycles_match(record.cycle, target_cycle):
        blockers.append("证据申请季与当前项目申请季不匹配。")
    allowed_scopes = FORMAL_SCOPE_BY_FIELD.get(field_name, {SourceScope.programme_detail})
    if record.source_scope not in allowed_scopes:
        blockers.append("来源 scope 不足以证明该项目字段。")
    if not record.source_url:
        blockers.append("缺少可追溯的来源 URL。")
    if not record.page_hash:
        blockers.append("缺少不可变页面快照 hash。")
    if not record.snapshot_url:
        blockers.append("缺少已保留的来源快照。")
    if not record.evidence_snippet:
        blockers.append("缺少字段级证据摘录。")
    if not record.reviewer_id or not record.review_decision_id:
        blockers.append("缺少独立审核者或审核决定 ID。")
    if record.binding_status != "matched":
        blockers.append("来源尚未被确认绑定到该项目。")
    if record.verified_at is None:
        blockers.append("缺少字段审核时间。")
    if str(record.value or "").strip() in {"", "NOT_PUBLISHED"}:
        blockers.append("官网尚未发布可用于该决策的字段值。")
    return blockers


def _unusable_provenance(
    records: list[FieldEvidenceRecord], target_cycle: str
) -> tuple[FactProvenanceStatus, list[str]]:
    if not records:
        return FactProvenanceStatus.UNVERIFIED, []
    if any(record.status == FieldVerificationStatus.conflicted for record in records):
        return FactProvenanceStatus.CONFLICTED, ["存在待裁决的来源冲突。"]
    if any(record.status == FieldVerificationStatus.not_published for record in records):
        return FactProvenanceStatus.NOT_PUBLISHED, ["官网明确未发布该字段。"]
    if any(record.status == FieldVerificationStatus.official_previous_cycle for record in records):
        return FactProvenanceStatus.REVIEWED_PREVIOUS, ["只存在往届官方来源；不能用于当前季硬决策。"]
    if any(
        record.status == FieldVerificationStatus.official_verified_current
        and not _cycles_match(record.cycle, target_cycle)
        for record in records
    ):
        return FactProvenanceStatus.STALE, ["可用来源属于其他申请季，当前季需重新核验。"]
    return FactProvenanceStatus.UNVERIFIED, []


def _catalog_value(program: Program, field_name: str) -> Any | None:
    requirements = program.requirements
    values: dict[str, Any] = {
        "institution": program.institution,
        "program_name": program.name,
        "official_program_url": str(program.official_program_url) if program.official_program_url else None,
        "application_url": str(program.application_url) if program.application_url else None,
        "deadline": program.deadline.isoformat() if hasattr(program.deadline, "isoformat") else program.deadline,
        "application_rounds": [item.model_dump(mode="json") for item in program.application_rounds],
        "tuition_hkd": program.tuition_hkd,
        "application_fee_hkd": program.application_fee_hkd,
        "min_gpa": requirements.min_gpa,
        "language_requirement": requirements.language,
        "required_backgrounds": requirements.required_backgrounds,
        "preferred_backgrounds": requirements.preferred_backgrounds,
        "prerequisites": requirements.prerequisites,
        "portfolio_required": requirements.portfolio_required,
        "work_experience_preferred": requirements.work_experience_preferred,
        "materials": program.materials,
    }
    return values.get(field_name)


def normalize_field_value(field_name: str, value: str | None) -> Any | None:
    """Normalize a reviewed field only when its decision unit is unambiguous.

    The function is shared by the human-review publisher so a record cannot be
    marked current/official by one layer and then rejected as ambiguous by the
    canonical resolver.  ``None`` means "retain as a candidate or reference,
    but do not use it in a hard decision".
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "NOT_PUBLISHED":
        return None
    if field_name in {"tuition_hkd", "application_fee_hkd"}:
        digits = re.sub(r"[^0-9.]", "", text.replace(",", ""))
        return int(float(digits)) if digits else None
    if field_name == "min_gpa":
        # The eligibility engine compares against a 100-point GPA.  An
        # official statement such as "3.0/4.0" is a real source fact but it
        # is *not* safely interchangeable with the project's 100-point
        # normalization rubric: universities can apply their own conversion.
        # Require an explicit 100-point value (or a reviewed structured value
        # whose scale is 100) before this field can generate a hard result.
        parsed = _parse_json(text)
        if isinstance(parsed, dict):
            value = parsed.get("value")
            scale = str(parsed.get("scale") or "").strip().lower()
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return None
            return numeric if scale in {"100", "100.0", "100-point", "100_point"} and 0 <= numeric <= 100 else None
        explicit_100 = re.search(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*(?:/\s*100|out\s+of\s+100|/100分)", text, flags=re.I)
        if explicit_100:
            numeric = float(explicit_100.group(1))
            return numeric if 0 <= numeric <= 100 else None
        # A plain value in the typical 100-point range is permitted only when
        # it has no competing GPA scale marker.  Reviewers can still retain
        # the original scale in the evidence snippet while publishing an
        # explicit structured normalized value.
        if re.search(r"(?:/\s*(?:4(?:\.0)?|5(?:\.0)?)\b|gpa\s*(?:4|5)(?:\.0)?\b)", text, flags=re.I):
            return None
        match = re.fullmatch(r"\s*(\d{2,3}(?:\.\d+)?)\s*", text)
        if not match:
            return None
        numeric = float(match.group(1))
        return numeric if 40 <= numeric <= 100 else None
    if field_name in {"portfolio_required", "work_experience_preferred"}:
        lower = text.lower()
        if lower in {"true", "yes", "required", "是", "需要"}:
            return True
        if lower in {"false", "no", "not required", "否", "不需要"}:
            return False
        return None
    if field_name == "language_requirement":
        parsed = _parse_json(text)
        if isinstance(parsed, dict):
            cleaned = {str(key).upper(): float(item) for key, item in parsed.items()}
            return cleaned or None
        pairs = re.findall(r"(IELTS|TOEFL|PTE)\s*[:>=-]?\s*(\d+(?:\.\d+)?)", text, flags=re.I)
        return {name.upper(): float(score) for name, score in pairs} or None
    if field_name in {
        "required_backgrounds",
        "preferred_backgrounds",
        "prerequisites",
        "materials",
        "application_rounds",
        "essay_prompts",
    }:
        parsed = _parse_json(text)
        parsed_list = isinstance(parsed, list)
        if parsed_list:
            values = [str(item).strip().lower().replace("_", " ") for item in parsed if str(item).strip()]
        else:
            values = [item.strip().lower().replace("_", " ") for item in re.split(r"[,;；\n]", text) if item.strip()]
        if field_name == "required_backgrounds":
            # ``check_program_eligibility`` intentionally has a finite,
            # auditable requirement taxonomy.  Do not turn an arbitrary prose
            # fragment from a crawler into a hard admissions predicate.
            allowed = {"computing", "business", "statistics", "engineering"}
            # An explicit JSON ``[]`` is a reviewable statement that no hard
            # background restriction applies.  It is distinct from an empty
            # crawler fragment, which remains unknown.
            if parsed_list and not values:
                return []
            return values if values and all(item in allowed for item in values) else None
        return values or None
    return text


def _parse_json(value: str) -> Any | None:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _cycles_match(value: str | None, target: str) -> bool:
    if not value:
        return False
    return _cycle_key(value) == _cycle_key(target)


def _cycle_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    normalized = normalized.replace("autumn", "fall").replace("fallterm", "fall")
    return normalized


def _record_sort_key(item: tuple[FieldEvidenceRecord, Any]) -> tuple[int, float, str]:
    record, _ = item
    verified = record.verified_at or record.extracted_at or datetime.min.replace(tzinfo=UTC)
    return (record.source_priority, -verified.timestamp(), record.evidence_id or "")


def _canonical_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _fact_id(program_id: str, cycle: str, field_name: str, evidence_id: str | None) -> str:
    raw = f"{program_id}|{cycle}|{field_name}|{evidence_id or 'missing'}"
    return "fact_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _conflict_id(program_id: str, cycle: str, field_name: str, values: set[str]) -> str:
    raw = "|".join([program_id, cycle, field_name, *sorted(values)])
    return "fact_conflict_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _stable_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
