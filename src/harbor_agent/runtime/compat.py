"""Adapters from new runtime state to legacy stage response models.

They preserve the existing student-facing API shapes while deriving every
value and trace entry from the supervisor runtime rather than replaying the
old fixed call chain.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

from harbor_agent.core.rules import display_gpa
from harbor_agent.models import (
    AgentStatus,
    AgentTraceEvent,
    ApplicationPlanResult,
    AssessmentResult,
    BackgroundStageResult,
    ConsultantPlanItem,
    ConsultantSchoolPlan,
    CriticReadiness,
    DataRefreshReport,
    EvidenceReview,
    FieldEvidenceRecord,
    NormalizedProfile,
    ProgramMatch,
    ProgramPlanResult,
    ProgramRefreshFinding,
    StoryCard,
    TimelineTask,
    WorkflowResult,
    WritingDraft,
    WritingPlanResult,
)
from harbor_agent.runtime.state import AgentState, WorkflowGoal, WorkflowStatus
from harbor_agent.services.agent_runtime import list_runtime_trace_events
from harbor_agent.services.claim_graph import build_claim_graph, claim_graph_passed
from harbor_agent.services.evidence_graph import build_program_trust_detail
from harbor_agent.services.formal_gate import CRITICAL_TIMELINE_FIELDS, program_field_gate
from harbor_agent.services.intent import build_intent_profile


def require_completed(state: AgentState) -> AgentState:
    if state.status != WorkflowStatus.COMPLETED:
        question = state.user_question or state.human_review_reason or "; ".join(state.errors)
        raise RuntimeError(f"runtime is {state.status.value}: {question or 'workflow needs more input'}")
    return state


def to_background(state: AgentState) -> BackgroundStageResult:
    state = require_completed(state)
    return BackgroundStageResult(
        workflow_id=state.workflow_id,
        profile=_profile(state),
        evidence=_evidence(state),
        assessment=_assessment(state),
        trace=_legacy_trace(state.workflow_id),
    )


def to_program_plan(state: AgentState) -> ProgramPlanResult:
    state = require_completed(state)
    profile = _profile(state)
    assessment = _assessment(state)
    matches = _matches(state)
    layers = _layer_program_matches(matches)
    return ProgramPlanResult(
        workflow_id=state.workflow_id,
        profile=profile,
        assessment=assessment,
        intent_profile=build_intent_profile(profile),
        recommendations=matches,
        candidate_pool=layers["candidate_pool"],
        focus_list=layers["focus_list"],
        application_mix=layers["application_mix"],
        final_candidates=layers["final_candidates"],
        core_candidates=layers["core_candidates"],
        related_candidates=layers["related_candidates"],
        blocked_candidates=layers["blocked_candidates"],
        consultant_plan=_build_consultant_plan(profile, assessment, layers, matches),
        trace=_legacy_trace(state.workflow_id),
    )


def to_application_plan(state: AgentState) -> ApplicationPlanResult:
    state = require_completed(state)
    selected = _selected_matches(state)
    return ApplicationPlanResult(
        workflow_id=state.workflow_id,
        selected_programs=selected,
        timeline=[TimelineTask.model_validate(item) for item in state.timeline],
        source_refresh=_source_refresh_summary(state, selected),
        review=_review_summary(state, selected),
        trace=_legacy_trace(state.workflow_id),
    )


def to_writing_plan(state: AgentState) -> WritingPlanResult:
    state = require_completed(state)
    if state.writing_draft is None:
        raise RuntimeError("runtime completed without writing draft")
    return WritingPlanResult(
        workflow_id=state.workflow_id,
        story_cards=[StoryCard.model_validate(item) for item in state.story_cards],
        writing=_writing_with_delivery_status(state),
        review=_review_summary(state),
        trace=_legacy_trace(state.workflow_id),
        critic_readiness=_critic_readiness(state),
        delivery_status=_delivery_status(state),
        formal_use_ready=bool((state.final_result or {}).get("formal_use_ready")),
        formal_blockers=_formal_blockers(state),
    )


def to_preliminary_writing_plan(state: AgentState) -> WritingPlanResult:
    """Expose a revisable draft while preserving a blocked formal delivery.

    Default mock mode is still useful for story-card collection and prose
    revision.  A source/ClaimGraph block must not turn that useful preview into
    a 500 or a fake formal pass, so this adapter deliberately emits the exact
    blocked readiness on the same legacy response shape.
    """

    if state.writing_draft is None:
        raise RuntimeError("runtime blocked before it produced a writing draft")
    review = _review_summary(state)
    return WritingPlanResult(
        workflow_id=state.workflow_id,
        story_cards=[StoryCard.model_validate(item) for item in state.story_cards],
        writing=_writing_with_delivery_status(state),
        review=review,
        trace=_legacy_trace(state.workflow_id),
        critic_readiness=_critic_readiness(state),
        delivery_status=_delivery_status(state),
        formal_use_ready=False,
        formal_blockers=_formal_blockers(state),
    )


def to_workflow_result(state: AgentState) -> WorkflowResult:
    state = require_completed(state)
    if state.writing_draft is None:
        raise RuntimeError("runtime completed without writing draft")
    return WorkflowResult(
        workflow_id=state.workflow_id,
        profile=_profile(state),
        evidence=_evidence(state),
        assessment=_assessment(state),
        recommendations=_matches(state),
        timeline=[TimelineTask.model_validate(item) for item in state.timeline],
        writing=_writing_with_delivery_status(state),
        review=_review_summary(state),
        trace=_legacy_trace(state.workflow_id),
    )


def _profile(state: AgentState) -> NormalizedProfile:
    if state.normalized_profile is None:
        raise RuntimeError("normalized profile missing")
    return NormalizedProfile.model_validate(state.normalized_profile)


def _evidence(state: AgentState) -> EvidenceReview:
    if state.evidence_review is None:
        raise RuntimeError("evidence review missing")
    return EvidenceReview.model_validate(state.evidence_review)


def _assessment(state: AgentState) -> AssessmentResult:
    if state.assessment is None:
        raise RuntimeError("assessment missing")
    return AssessmentResult.model_validate(state.assessment)


def _matches(state: AgentState) -> list[ProgramMatch]:
    return [ProgramMatch.model_validate(_normalize_legacy_match(item)) for item in state.program_matches.values()]


def _selected_matches(state: AgentState) -> list[ProgramMatch]:
    """Return the portfolio persisted by MatchingAgent in its original order."""

    if state.selected_matches:
        return [ProgramMatch.model_validate(_normalize_legacy_match(item)) for item in state.selected_matches]
    selected_ids = set(state.selected_program_ids)
    return [item for item in _matches(state) if item.program.id in selected_ids]


def _review_summary(state: AgentState, matches: list[ProgramMatch] | None = None) -> dict[str, Any]:
    """Project the runtime's structured decision without recreating a pass.

    This compatibility response is consumed by older stage endpoints.  It may
    add explanatory fields, but it must never turn a clean-looking
    ``review_flags`` array into a formal success.  ClaimGraph, Critic readiness
    and the Supervisor's canonical final result are the only success signals.
    """

    reviewed_matches = matches if matches is not None else (_selected_matches(state) or _matches(state))
    hard_violations = [item.program.id for item in reviewed_matches if not item.hard_rule_passed]
    timeline_blockers: dict[str, list[str]] = {}
    previous_cycle_reference_fields: dict[str, list[str]] = {}
    for item in reviewed_matches:
        gate = program_field_gate(item.program)
        runtime_missing = list(state.fields_needing_verification.get(item.program.id, []))
        blockers = list(dict.fromkeys([*runtime_missing, *list(gate["missing_or_blocked_fields"])]))
        if blockers:
            timeline_blockers[item.program.id] = blockers
        previous_fields = list(gate["previous_cycle_fields"])
        if previous_fields:
            previous_cycle_reference_fields[item.program.id] = previous_fields

    programs_with_missing_or_blocked_fields = list(timeline_blockers)
    programs_requiring_current_cycle_review = sorted(
        set(programs_with_missing_or_blocked_fields) | set(previous_cycle_reference_fields)
    )
    writing = WritingDraft.model_validate(state.writing_draft) if state.writing_draft else None
    writing_required = state.goal in {WorkflowGoal.WRITING, WorkflowGoal.FULL_APPLICATION_PLAN}
    graph = (
        build_claim_graph(writing, reviewed_matches, student_facts=state.story_cards)
        if writing is not None
        else None
    )
    claim_grounding_ready = claim_graph_passed(graph)
    writing_ready = (
        not writing_required
        or (
            state.writing_ready
            and claim_grounding_ready
        )
    )
    writing_review = (
        "本次工作流未请求文书产出；文书阶段仍需逐句绑定学生事实和项目官网依据。"
        if writing is None
        else (
            "文书尚未通过独立 ClaimGraph 验证，不能作为最终提交稿。"
            if writing_required and not writing_ready
            else "文书 ClaimGraph 已通过；仍需以 Critic 的正式交付状态为准。"
        )
    )
    runtime_final = state.final_result if isinstance(state.final_result, dict) else {}
    critic_readiness = str(state.working_memory.get("critic_readiness") or "")
    critic_blockers = _string_list(state.working_memory.get("critic_blockers"))
    canonical_formal_ready = bool(runtime_final.get("formal_use_ready"))
    passed = (
        not hard_violations
        and not programs_requiring_current_cycle_review
        and not state.verification_conflicts
        and writing_ready
        and critic_readiness == CriticReadiness.FORMAL_PASS.value
        and canonical_formal_ready
    )
    if passed:
        status_label = "可进入正式申请使用"
    elif critic_readiness == CriticReadiness.PRELIMINARY_COMPLETE.value:
        status_label = "仅完成探索/准备交付；当前季正式字段仍未齐全"
    elif critic_readiness == CriticReadiness.BLOCKED.value:
        status_label = "正式交付已被阻断，需要新的来源、重写或人工审核"
    else:
        status_label = "关键字段或 ClaimGraph 核验完成前不能作为正式申请计划"
    blockers = list(dict.fromkeys([
        *critic_blockers,
        *(graph.blockers if graph is not None else ([] if not writing_required else ["缺少 ClaimGraph。"])),
    ]))
    return {
        "passed": passed,
        "status_label": status_label,
        "hard_rule_violations": hard_violations,
        "programs_requiring_data_review": programs_requiring_current_cycle_review,
        "programs_with_missing_or_blocked_fields": programs_with_missing_or_blocked_fields,
        "programs_requiring_current_cycle_review": programs_requiring_current_cycle_review,
        "timeline_blockers": timeline_blockers,
        "previous_cycle_reference_fields": previous_cycle_reference_fields,
        "required_timeline_fields": CRITICAL_TIMELINE_FIELDS,
        "writing_review": writing_review,
        "claim_graph": graph.model_dump(mode="json") if graph is not None else None,
        "claim_grounding_ready": claim_grounding_ready,
        "writing_ready": state.writing_ready,
        "verification_conflicts": state.verification_conflicts,
        "critic_readiness": critic_readiness or None,
        "delivery_status": str(runtime_final.get("delivery_status") or critic_readiness or "UNREVIEWED"),
        "blockers": blockers,
        "formal_use_ready": passed,
        "human_gates": [
            "正式提交倒推必须同时具备项目详情页、截止日期、申请入口、语言要求、材料清单和学费的字段级当前季官网证据。",
            "只有上一申请季证据时，只能生成带年份标注的准备动作，不能生成正式 DDL 倒推。",
            "社区、GitHub、论坛和第三方表格只作为线索，不能替代学校官网要求。",
            "学校定制文书句必须绑定项目官网、PDF/FAQ 或网申系统证据。",
        ],
    }


def _writing_with_delivery_status(state: AgentState) -> WritingDraft:
    """Return a draft annotated from live runtime state, not prose hints."""

    if state.writing_draft is None:
        raise RuntimeError("writing draft missing")
    draft = WritingDraft.model_validate(state.writing_draft)
    matches = _selected_matches(state) or _matches(state)
    graph = build_claim_graph(draft, matches, student_facts=state.story_cards)
    claim_grounding_ready = state.writing_ready and claim_graph_passed(graph)
    runtime_final = state.final_result if isinstance(state.final_result, dict) else {}
    critic_readiness = str(state.working_memory.get("critic_readiness") or "")
    formal_use_ready = bool(runtime_final.get("formal_use_ready")) and (
        critic_readiness == CriticReadiness.FORMAL_PASS.value
    ) and claim_grounding_ready
    blockers = list(dict.fromkeys([
        *list(graph.blockers),
        *_string_list(state.working_memory.get("critic_blockers")),
        *_string_list(runtime_final.get("blockers")),
    ]))
    if not formal_use_ready and not blockers:
        blockers.append("当前文书未取得 Supervisor/Critic 的正式交付许可。")
    return draft.model_copy(
        update={
            "claim_graph": graph,
            "claim_grounding_ready": claim_grounding_ready,
            "delivery_status": _draft_delivery_status(state),
            "formal_use_ready": formal_use_ready,
            "formal_blockers": blockers,
        }
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _critic_readiness(state: AgentState) -> CriticReadiness | None:
    raw = str(state.working_memory.get("critic_readiness") or "")
    try:
        return CriticReadiness(raw) if raw else None
    except ValueError:
        return None


def _delivery_status(state: AgentState) -> str:
    final = state.final_result if isinstance(state.final_result, dict) else {}
    return str(final.get("delivery_status") or state.working_memory.get("critic_readiness") or "UNREVIEWED")


def _draft_delivery_status(state: AgentState) -> CriticReadiness | str:
    """Coerce the runtime string to the draft model's closed delivery enum."""

    raw = _delivery_status(state)
    try:
        return CriticReadiness(raw)
    except ValueError:
        return "UNREVIEWED"


def _formal_blockers(state: AgentState) -> list[str]:
    final = state.final_result if isinstance(state.final_result, dict) else {}
    return list(dict.fromkeys([
        *_string_list(state.working_memory.get("critic_blockers")),
        *_string_list(final.get("blockers")),
    ]))


def _source_refresh_summary(
    state: AgentState,
    selected: list[ProgramMatch],
) -> DataRefreshReport | None:
    """Map VerificationAgent snapshots to the established refresh-report shape.

    No source is fetched again here. The data comes from the field-level trust
    records used by VerificationAgent, keeping legacy clients compatible while
    retaining the Runtime as the only workflow executor.
    """

    if not selected:
        return None

    findings: list[ProgramRefreshFinding] = []
    records: list[FieldEvidenceRecord] = []
    stale_program_ids: list[str] = []
    review_queue_size = 0
    formal_ready_program_count = 0
    formal_blocker_count = 0
    for match in selected:
        program_id = match.program.id
        snapshot = state.verified_program_fields.get(program_id, {})
        snapshot_records = snapshot.get("field_records", []) if isinstance(snapshot, dict) else []
        try:
            field_records = [FieldEvidenceRecord.model_validate(item) for item in snapshot_records]
        except (TypeError, ValueError):
            field_records = []
        trust = build_program_trust_detail(match.program)
        if not field_records:
            field_records = trust.field_records
        required_fields = list(state.fields_needing_verification.get(program_id, []))
        if not required_fields and isinstance(snapshot, dict):
            required_fields = list(snapshot.get("fields_requiring_review", []))
        if not required_fields:
            required_fields = list(trust.fields_requiring_review)
        review_queue_size += len(required_fields)
        if trust.stale_or_reference_fields:
            stale_program_ids.append(program_id)
        formal_ready = bool(getattr(trust, "production_ready", False))
        if formal_ready:
            formal_ready_program_count += 1
        formal_blocker_count += len(trust.fields_requiring_review)
        resolved_official_url = None
        for record in field_records:
            if (
                record.field_name == "official_program_url"
                and record.status.value == "OFFICIAL_VERIFIED_CURRENT"
                and not record.review_required
                and record.source_url
            ):
                resolved_official_url = record.source_url
                break
        findings.append(
            ProgramRefreshFinding(
                program_id=program_id,
                institution=match.program.institution,
                program_name=match.program.name_zh or match.program.name,
                data_status=("VERIFIED" if formal_ready else "PENDING_REVIEW"),
                official_url=resolved_official_url,
                source_ids=list(dict.fromkeys(str(record.source_url) for record in field_records if record.source_url))[:8],
                fields_requiring_review=required_fields,
                summary=trust.source_warning,
                next_actions=(
                    ["由人工核对项目官网当前申请季字段后再发布正式计划。"]
                    if required_fields
                    else ["继续保留当前季官网证据快照并在提交前复核。"]
                ),
            )
        )
        records.extend(field_records)

    selected_ids = [item.program.id for item in selected]
    return DataRefreshReport(
        run_id=f"{state.workflow_id}:verification",
        mode="dry_run",
        checked_at=datetime.now(UTC),
        region="ALL",
        selected_program_ids=selected_ids,
        sources_checked=len(selected_ids),
        official_sources_checked=len(selected_ids),
        community_sources_checked=0,
        program_findings=findings,
        field_evidence_records=records,
        parser_plan=[
            "VerificationAgent 读取字段级可信度记录。",
            "系统将缺失或往届字段保留在人工审核队列，未重新请求或发布来源。",
        ],
        review_queue_size=review_queue_size,
        stale_program_ids=stale_program_ids,
        human_review_required=bool(review_queue_size or state.verification_conflicts),
        summary=f"Runtime VerificationAgent checked {len(selected_ids)} selected programmes.",
        next_actions=["对标记字段核对学校官网当前申请季原文，再进入正式提交倒推。"],
        truth_scope="runtime_evidence_projection",
        formal_ready_program_count=formal_ready_program_count,
        formal_blocker_count=formal_blocker_count,
    )


def _layer_program_matches(matches: list[ProgramMatch]) -> dict[str, list[ProgramMatch]]:
    viable = [item for item in matches if item.tier != "not_recommended"]
    core = [item for item in viable if item.match_category == "core"]
    related = [item for item in viable if item.match_category == "related"]
    general = [item for item in viable if item.match_category == "general"]
    intent_blocked = [item for item in matches if item.match_category == "blocked"]
    rule_blocked = [
        item
        for item in matches
        if item.tier == "not_recommended" and item.match_category != "blocked"
    ]
    blocked = intent_blocked + rule_blocked
    return {
        "candidate_pool": (core + related + general)[:50],
        "focus_list": (core[:12] + related[:3] + general[:2])[:15],
        "application_mix": _balanced_application_mix(core, related, viable),
        "final_candidates": [item for item in viable if item.formal_recommendation][:4],
        "core_candidates": core[:24],
        "related_candidates": related[:24],
        "blocked_candidates": blocked[:12],
    }


def _balanced_application_mix(
    core: list[ProgramMatch],
    related: list[ProgramMatch],
    viable: list[ProgramMatch],
) -> list[ProgramMatch]:
    selected: list[ProgramMatch] = []
    selected.extend(_pick_diverse([item for item in core if item.strategy_band == "reach"], 4))
    selected.extend(_pick_diverse([item for item in core if item.strategy_band == "target"], 4))
    selected.extend(_pick_diverse([item for item in core if item.strategy_band == "safer"], 3))
    if len(selected) < 8:
        selected.extend([item for item in core if item not in selected][: 8 - len(selected)])
    if len(selected) < 6:
        selected.extend([item for item in related if item.strategy_band in {"target", "safer"}][: 6 - len(selected)])
    if len(selected) < 6:
        selected.extend([item for item in related if item not in selected][: 6 - len(selected)])

    deduped: list[ProgramMatch] = []
    seen: set[str] = set()
    for item in selected:
        if item.program.id in seen:
            continue
        deduped.append(item)
        seen.add(item.program.id)
        if len(deduped) == 10:
            break
    return sorted(deduped, key=_application_mix_sort_key)


def _application_mix_sort_key(item: ProgramMatch) -> tuple[int, int, int]:
    band_order = {"reach": 0, "target": 1, "safer": 2, "candidate": 3, "blocked": 4}
    category_order = {"core": 0, "related": 1, "general": 2, "blocked": 3}
    return (
        band_order.get(item.strategy_band, 9),
        category_order.get(item.match_category, 9),
        -item.fit_score,
    )


def _pick_diverse(items: list[ProgramMatch], limit: int) -> list[ProgramMatch]:
    picked: list[ProgramMatch] = []
    seen_institutions: set[str] = set()
    for item in items:
        if item.program.institution in seen_institutions:
            continue
        picked.append(item)
        seen_institutions.add(item.program.institution)
        if len(picked) == limit:
            return picked
    for item in items:
        if item in picked:
            continue
        picked.append(item)
        if len(picked) == limit:
            return picked
    return picked


def _build_consultant_plan(
    profile: NormalizedProfile,
    assessment: AssessmentResult,
    layers: dict[str, list[ProgramMatch]],
    matches: list[ProgramMatch],
) -> ConsultantSchoolPlan:
    application_mix = layers["application_mix"]
    band_counts = {
        "冲刺": sum(1 for item in application_mix if item.strategy_band == "reach"),
        "主申": sum(1 for item in application_mix if item.strategy_band == "target"),
        "相对稳妥": sum(1 for item in application_mix if item.strategy_band == "safer"),
        "候选": sum(1 for item in application_mix if item.strategy_band == "candidate"),
    }
    interests = _student_direction_label(profile.discipline_tags) or "目标方向待补充"
    language = (
        f"{profile.language.test} {profile.language.overall}"
        if profile.language.test != "NONE" and profile.language.overall
        else "语言成绩待补充"
    )
    profile_summary = (
        f"{profile.education.school_tier} 背景，{profile.education.major}，"
        f"GPA {display_gpa(profile)}，{language}，目标方向：{interests}。"
    )
    strategy_summary = (
        "本方案按学校层级、专业方向匹配、GPA/语言硬条件、经历相关性和数据可信度分层。"
        "默认只给出 6-10 个可行动项目；港三/新二等高挑战项目进入冲刺，"
        "城大/理工/SMU 等同层级项目作为主申，浸会/岭南等只在方向匹配时作为相对稳妥或候选。"
    )
    data_disclaimer = (
        "当前方案可以用于选校讨论和准备材料；截止日期、学费、语言要求、材料清单和申请入口，"
        "必须以学校官网当季原文为准。系统会把需核验的信息明确标出来，不把草案包装成最终结论。"
    )
    deferred = [
        f"{item.program.institution_zh or item.program.institution} {item.program.name_zh or item.program.name}："
        f"{item.risks[0] if item.risks else '方向或硬条件不适合当前方案。'}"
        for item in matches
        if item.tier == "not_recommended"
    ][:6]
    next_actions = [
        "先确认目标方向是否以 CS/AI/Data 为主，避免商科弱相关项目挤占申请名额。",
        "上传成绩单或填写核心课程成绩后，重新计算课程匹配和先修课风险。",
        "对推荐清单核对项目来源，优先找到项目详情页、申请系统和 PDF/FAQ。",
        "学生从项目库勾选最终项目清单后，再排逐项目日期和材料动作。",
    ]
    if assessment.decision_field_coverage < 70:
        next_actions.insert(1, "当前关键决策字段覆盖不足，正式定校前需要补充排名、课程、经历深度和语言单项。")
    return ConsultantSchoolPlan(
        title="港新硕士择校方案初版",
        profile_summary=profile_summary,
        strategy_summary=strategy_summary,
        data_disclaimer=data_disclaimer,
        band_counts=band_counts,
        items=[_consultant_item(item) for item in application_mix],
        rejected_or_deferred=deferred,
        next_actions=next_actions[:6],
    )


def _consultant_item(item: ProgramMatch) -> ConsultantPlanItem:
    band = {
        "reach": "冲刺",
        "target": "主申",
        "safer": "相对稳妥",
        "candidate": "候选",
        "blocked": "暂不建议",
    }[item.strategy_band]
    explanation = item.explanation
    fit_parts: list[str] = []
    if explanation:
        fit_parts.extend(
            [
                f"硬条件{explanation.hard_condition}",
                f"学术{explanation.academic_match}",
                f"课程{explanation.course_match}",
                f"经历{explanation.experience_match}",
                f"预算{explanation.budget_match}",
            ]
        )
    return ConsultantPlanItem(
        program_id=item.program.id,
        band=band,
        institution=item.program.institution_zh or item.program.institution,
        program_name=item.program.name_zh or item.program.name,
        why_this_band=item.consultant_note or "按背景竞争力、学校层级和方向匹配分入当前档位。",
        student_fit="；".join(fit_parts) or "等待背景字段补充后判断。",
        main_risk=item.risks[0] if item.risks else "未发现明显风险，但仍需打开学校官网确认。",
        next_action=item.actions[0] if item.actions else "打开学校官网详情页，确认当前申请季信息。",
        data_warning=item.source_warning or "当前申请季信息仍需学校官网确认。",
        official_url=item.program.official_program_url or item.program.source.url,
        application_url=item.program.application_url,
    )


def _student_direction_label(tags: list[str]) -> str:
    labels = {
        "artificial_intelligence": "人工智能",
        "computer_science": "计算机",
        "data_science": "数据科学",
        "software_engineering": "软件工程",
        "cyber_security": "网络安全",
        "business": "商科",
        "engineering": "工程",
        "communication": "传媒传播",
        "education_language": "教育/语言",
        "design_built_environment": "建筑/城市/设计",
        "law_policy": "法律/公共政策",
        "life_health": "生命健康",
    }
    return " / ".join(labels.get(tag, str(tag).replace("_", " ")) for tag in tags[:4])


def _legacy_trace(workflow_id: str) -> list[AgentTraceEvent]:
    """Group actual runtime events for legacy clients; never manufacture tool names."""

    grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for event in list_runtime_trace_events(workflow_id):
        agent = event.get("agent_name")
        if not agent or agent == "SupervisorAgent":
            continue
        bucket = grouped.setdefault(
            agent,
            {
                "started_at": event.get("started_at"),
                "finished_at": event.get("finished_at"),
                "status": AgentStatus.completed,
                "input_summary": event.get("input_summary") or "runtime execution",
                "output_summary": event.get("output_summary") or "",
                "tool_calls": [],
                "model": event.get("model") or "runtime",
                "cost_usd": event.get("cost_usd"),
                "needs_human_reason": None,
            },
        )
        if event.get("event_type") == "TOOL_CALL" and event.get("tool_name"):
            bucket["tool_calls"].append(event["tool_name"])
        if event.get("event_type") == "ERROR":
            bucket["status"] = AgentStatus.failed
            bucket["output_summary"] = event.get("error_message") or "runtime error"
        if event.get("event_type") == "HUMAN_WAIT":
            bucket["status"] = AgentStatus.needs_human
            bucket["needs_human_reason"] = event.get("output_summary")
        bucket["finished_at"] = event.get("finished_at") or bucket["finished_at"]
    return [
        AgentTraceEvent(
            node=name,
            status=item["status"],
            started_at=datetime.fromisoformat(item["started_at"]) if isinstance(item["started_at"], str) else datetime.now(UTC),
            finished_at=datetime.fromisoformat(item["finished_at"]) if isinstance(item["finished_at"], str) else datetime.now(UTC),
            input_summary=item["input_summary"],
            output_summary=item["output_summary"],
            tool_calls=list(dict.fromkeys(item["tool_calls"])),
            model=item["model"],
            cost_usd=item["cost_usd"],
            needs_human_reason=item["needs_human_reason"],
        )
        for name, item in grouped.items()
    ]

def _normalize_legacy_match(raw: dict[str, Any]) -> dict[str, Any]:
    """Translate persisted safe bands before validating the new response model."""
    payload = dict(raw)
    if payload.get("tier") == "safe":
        payload["tier"] = "safer"
    if payload.get("strategy_band") == "safe":
        payload["strategy_band"] = "safer"
    return payload
