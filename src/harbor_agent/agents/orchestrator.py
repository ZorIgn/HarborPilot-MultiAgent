from __future__ import annotations

from datetime import date
from uuid import uuid4

from harbor_agent.agents.evaluation import EvaluationAgent
from harbor_agent.agents.data_refresh import DataRefreshAgent
from harbor_agent.agents.data_acquisition import ProgramDataAcquisitionAgent
from harbor_agent.agents.source_crawl_queue import SourceCrawlQueueAgent
from harbor_agent.agents.evidence import EvidenceAgent
from harbor_agent.agents.matching import SchoolMatchingAgent
from harbor_agent.agents.profile import ProfileAgent
from harbor_agent.agents.program_intelligence import ProgramIntelligenceAgent
from harbor_agent.agents.review import ReviewAgent
from harbor_agent.agents.story_card import StoryCardAgent
from harbor_agent.agents.timeline import TimelineAgent
from harbor_agent.agents.writing import WritingAgent
from harbor_agent.core.llm import LLMProvider
from harbor_agent.core.rules import display_gpa
from harbor_agent.core.trace import TraceRecorder
from harbor_agent.models import (
    ApplicantProfileInput,
    ApplicationPlanResult,
    ConsultantPlanItem,
    ConsultantSchoolPlan,
    BackgroundStageResult,
    DataAcquisitionReport,
    DataAcquisitionRequest,
    DataRefreshReport,
    DataRefreshRequest,
    CrawlQueueReport,
    CrawlQueueRequest,
    ProgramPlanResult,
    QuestionnaireResponse,
    WorkflowResult,
    WritingPlanResult,
)
from harbor_agent.services.intent import build_intent_profile


class WorkflowOrchestrator:
    """Coordinates specialized agents through admissions business stages."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm
        self.profile_agent = ProfileAgent()
        self.data_refresh_agent = DataRefreshAgent(llm)
        self.data_acquisition_agent = ProgramDataAcquisitionAgent()
        self.source_crawl_queue_agent = SourceCrawlQueueAgent()
        self.evidence_agent = EvidenceAgent()
        self.evaluation_agent = EvaluationAgent(llm)
        self.program_agent = ProgramIntelligenceAgent()
        self.matching_agent = SchoolMatchingAgent(llm)
        self.timeline_agent = TimelineAgent()
        self.writing_agent = WritingAgent(llm)
        self.story_card_agent = StoryCardAgent()
        self.review_agent = ReviewAgent()

    def run_background_stage(self, payload: ApplicantProfileInput) -> BackgroundStageResult:
        workflow_id = f"wf_{uuid4().hex[:12]}"
        trace = TraceRecorder(workflow_id)

        profile, evidence, assessment = self._profile_evidence_assessment(payload, trace)

        return BackgroundStageResult(
            workflow_id=workflow_id,
            profile=profile,
            evidence=evidence,
            assessment=assessment,
            trace=trace.events,
        )

    def run_program_plan_stage(self, payload: ApplicantProfileInput) -> ProgramPlanResult:
        workflow_id = f"wf_{uuid4().hex[:12]}"
        trace = TraceRecorder(workflow_id)

        profile, _, assessment = self._profile_evidence_assessment(payload, trace)
        matches = self._program_matching(profile, assessment, trace)
        layers = _layer_program_matches(matches)

        return ProgramPlanResult(
            workflow_id=workflow_id,
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
            trace=trace.events,
        )

    def run_application_plan_stage(
        self,
        payload: ApplicantProfileInput,
        selected_program_ids: list[str],
    ) -> ApplicationPlanResult:
        workflow_id = f"wf_{uuid4().hex[:12]}"
        trace = TraceRecorder(workflow_id)

        profile, _, assessment = self._profile_evidence_assessment(payload, trace)
        matches = self._program_matching(profile, assessment, trace)

        with trace.span(
            "DataRefreshAgent",
            f"selected={selected_program_ids}",
            tool_calls=["source_registry.lookup", "official_url_freshness_dry_run", "field_review_queue"],
            model=self.llm.name,
        ) as span:
            source_refresh = self.data_refresh_agent.run(
                DataRefreshRequest(
                    selected_program_ids=selected_program_ids,
                    dry_run=True,
                    use_llm=self.llm.name != "mock",
                    max_sources=24,
                )
            )
            span["output_summary"] = (
                f"{source_refresh.sources_checked} sources checked; "
                f"{len(source_refresh.program_findings)} programs require source review"
            )

        with trace.span(
            "ProgramIntelligenceAgent",
            f"selected={selected_program_ids}",
            tool_calls=["source_freshness_check", "page_hash_diff", "requirement_schema_validator"],
        ) as span:
            selected = self.program_agent.refresh_selected(matches, selected_program_ids, source_refresh)
            span["output_summary"] = f"{len(selected)} selected programs queued for official verification"

        with trace.span(
            "TimelineAgent",
            f"{len(selected)} selected programs",
            tool_calls=["deadline_backplanner", "shared_task_merger"],
        ) as span:
            timeline = self.timeline_agent.run(selected, today=date.today())
            span["output_summary"] = f"{len(timeline)} timeline tasks generated"

        placeholder_writing = self.writing_agent.run(profile, selected)
        with trace.span(
            "ReviewAgent",
            "selected program plan",
            tool_calls=["official_field_gate", "timeline_gate"],
        ) as span:
            review = self.review_agent.run(selected, placeholder_writing)
            span["output_summary"] = "passed" if review["passed"] else "needs human review"

        return ApplicationPlanResult(
            workflow_id=workflow_id,
            selected_programs=selected,
            timeline=timeline,
            source_refresh=source_refresh,
            review=review,
            trace=trace.events,
        )

    def run_data_refresh_stage(self, request: DataRefreshRequest) -> DataRefreshReport:
        return self.data_refresh_agent.run(request)

    def run_data_acquisition_stage(self, request: DataAcquisitionRequest) -> DataAcquisitionReport:
        return self.data_acquisition_agent.run(request)

    def run_crawl_queue_stage(self, request: CrawlQueueRequest) -> CrawlQueueReport:
        return self.source_crawl_queue_agent.run(request)

    def run_writing_plan_stage(
        self,
        payload: ApplicantProfileInput,
        questionnaire: QuestionnaireResponse,
        selected_program_ids: list[str],
        document_type: str = "PS",
    ) -> WritingPlanResult:
        workflow_id = f"wf_{uuid4().hex[:12]}"
        trace = TraceRecorder(workflow_id)

        profile, _, assessment = self._profile_evidence_assessment(payload, trace)
        matches = self._program_matching(profile, assessment, trace)
        selected = [item for item in matches if item.program.id in selected_program_ids]

        with trace.span(
            "StoryCardAgent",
            f"profile={profile.profile_id}",
            tool_calls=["questionnaire_gap_check", "star_story_builder"],
        ) as span:
            story_cards = self.story_card_agent.run(questionnaire)
            span["output_summary"] = f"{len(story_cards)} story cards generated"

        with trace.span(
            "WritingAgent",
            f"profile={profile.profile_id}; document_type={document_type}",
            tool_calls=["fact_binding_builder", "outline_planner"],
            model=self.llm.name,
        ) as span:
            writing = self.writing_agent.run_from_story_cards(
                profile,
                selected,
                story_cards,
                document_type=document_type,
            )
            span["output_summary"] = f"{len(writing.outline)} outline sections; {len(writing.fact_bindings)} bindings"

        with trace.span(
            "ReviewAgent",
            "story cards and writing outline",
            tool_calls=["fact_binding_gate", "official_program_claim_gate"],
        ) as span:
            review = self.review_agent.run(selected, writing)
            span["output_summary"] = "passed" if review["passed"] else "needs human review"

        return WritingPlanResult(
            workflow_id=workflow_id,
            story_cards=story_cards,
            writing=writing,
            review=review,
            trace=trace.events,
        )

    def run_assessment(self, payload: ApplicantProfileInput) -> WorkflowResult:
        workflow_id = f"wf_{uuid4().hex[:12]}"
        trace = TraceRecorder(workflow_id)

        profile, evidence, assessment = self._profile_evidence_assessment(payload, trace)
        matches = self._program_matching(profile, assessment, trace)

        with trace.span(
            "TimelineAgent",
            f"{len(matches)} matches",
            tool_calls=["deadline_backplanner", "shared_task_merger"],
        ) as span:
            timeline = self.timeline_agent.run(matches, today=date.today())
            span["output_summary"] = f"{len(timeline)} timeline tasks generated"

        with trace.span(
            "WritingAgent",
            f"profile={profile.profile_id}",
            tool_calls=["fact_binding_builder"],
            model=self.llm.name,
        ) as span:
            writing = self.writing_agent.run(profile, matches)
            span["output_summary"] = f"{len(writing.outline)} outline sections; {len(writing.fact_bindings)} bindings"

        with trace.span(
            "ReviewAgent",
            "match plan and writing draft",
            tool_calls=["hard_rule_gate", "fact_binding_gate"],
        ) as span:
            review = self.review_agent.run(matches, writing)
            span["output_summary"] = "passed" if review["passed"] else "needs human review"

        return WorkflowResult(
            workflow_id=workflow_id,
            profile=profile,
            evidence=evidence,
            assessment=assessment,
            recommendations=matches,
            timeline=timeline,
            writing=writing,
            review=review,
            trace=trace.events,
        )

    def _profile_evidence_assessment(
        self,
        payload: ApplicantProfileInput,
        trace: TraceRecorder,
    ):
        with trace.span(
            "ProfileAgent",
            f"{payload.education.school}, {payload.education.major}, cycle={payload.target_cycle}",
            tool_calls=["taxonomy_mapper", "profile_completeness"],
        ) as span:
            profile = self.profile_agent.run(payload)
            span["output_summary"] = (
                f"{profile.profile_completeness}% complete; tags={','.join(profile.discipline_tags)}"
            )

        with trace.span(
            "EvidenceAgent",
            f"profile={profile.profile_id}",
            tool_calls=["evidence_level_counter", "confirmation_queue"],
        ) as span:
            evidence = self.evidence_agent.run(profile)
            span["output_summary"] = (
                f"{evidence.verified_fact_ratio}% confirmed/verified; "
                f"{len(evidence.recommended_uploads)} uploads recommended"
            )

        with trace.span(
            "EvaluationAgent",
            f"profile={profile.profile_id}",
            tool_calls=["rules.evaluate_general_profile"],
            model=self.llm.name,
        ) as span:
            assessment = self.evaluation_agent.run(profile)
            span["output_summary"] = (
                f"field_coverage={assessment.decision_field_coverage}%; "
                f"evidence={assessment.evidence_coverage}%; actions={len(assessment.actions)}"
            )
        return profile, evidence, assessment

    def _program_matching(self, profile, assessment, trace: TraceRecorder):
        with trace.span(
            "ProgramIntelligenceAgent",
            f"regions={profile.target_regions}; tags={profile.discipline_tags}",
            tool_calls=["official_source_registry", "community_signal_recall", "program_catalog.recall"],
        ) as span:
            candidates = self.program_agent.run(profile)
            span["output_summary"] = f"{len(candidates)} candidate programs recalled"

        with trace.span(
            "SchoolMatchingAgent",
            f"{len(candidates)} candidates",
            tool_calls=["rules.check_program_eligibility", "matching_score_service", "unverified_data_gate"],
        ) as span:
            matches = self.matching_agent.run(profile, assessment, candidates)
            span["output_summary"] = (
                f"{sum(1 for item in matches if item.hard_rule_passed)} eligible; "
                f"{sum(1 for item in matches if item.tier == 'insufficient_info')} candidate-only; "
                f"{sum(1 for item in matches if item.tier == 'not_recommended')} blocked"
            )
        return matches


def _layer_program_matches(
    matches,
):
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
    candidate_pool = (core + related + general)[:50]
    focus_list = (core[:12] + related[:3] + general[:2])[:15]
    application_mix = _balanced_application_mix(core, related, viable)
    final_candidates = [item for item in viable if item.formal_recommendation][:4]
    return {
        "candidate_pool": candidate_pool,
        "focus_list": focus_list,
        "application_mix": application_mix,
        "final_candidates": final_candidates,
        "core_candidates": core[:24],
        "related_candidates": related[:24],
        "blocked_candidates": blocked[:12],
    }


def _balanced_application_mix(core, related, viable):
    selected = []
    selected.extend(_pick_diverse([item for item in core if item.strategy_band == "reach"], 4))
    selected.extend(_pick_diverse([item for item in core if item.strategy_band == "target"], 4))
    selected.extend(_pick_diverse([item for item in core if item.strategy_band == "safe"], 3))
    if len(selected) < 8:
        selected.extend([item for item in core if item not in selected][: 8 - len(selected)])
    if len(selected) < 6:
        selected.extend([item for item in related if item.strategy_band in {"target", "safe"}][: 6 - len(selected)])
    if len(selected) < 6:
        selected.extend([item for item in viable if item not in selected][: 6 - len(selected)])

    deduped = []
    seen = set()
    for item in selected:
        if item.program.id in seen:
            continue
        deduped.append(item)
        seen.add(item.program.id)
        if len(deduped) == 10:
            break
    return sorted(deduped, key=_application_mix_sort_key)


def _application_mix_sort_key(item):
    band_order = {"reach": 0, "target": 1, "safe": 2, "candidate": 3, "blocked": 4}
    category_order = {"core": 0, "related": 1, "general": 2, "blocked": 3}
    return (band_order.get(item.strategy_band, 9), category_order.get(item.match_category, 9), -item.fit_score)


def _pick_diverse(items, limit: int):
    picked = []
    seen_institutions = set()
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


def _build_consultant_plan(profile, assessment, layers, matches) -> ConsultantSchoolPlan:
    application_mix = layers["application_mix"]
    band_counts = {
        "冲刺": sum(1 for item in application_mix if item.strategy_band == "reach"),
        "主申": sum(1 for item in application_mix if item.strategy_band == "target"),
        "保底": sum(1 for item in application_mix if item.strategy_band == "safe"),
        "候选": sum(1 for item in application_mix if item.strategy_band == "candidate"),
    }
    interests = _student_direction_label(profile.discipline_tags) or "目标方向待确认"
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
        "本方案按院校挑战度、专业方向匹配、GPA/语言硬条件、经历相关性和数据可信度分层。"
        "默认只给出 6-10 个可行动项目；港三/新二等高挑战项目进入冲刺，"
        "城大/理工/SMU 等同层级项目作为主申，浸会/岭南等只在方向匹配时作为保底或候选。"
    )
    data_disclaimer = (
        "当前方案可以用于选校讨论和准备材料；截止日期、学费、语言要求、材料清单和申请入口，"
        "必须以学校官网当季原文为准。系统会把未确认的信息明确标出来，不把草案包装成最终结论。"
    )
    items = [_consultant_item(item) for item in application_mix]
    deferred = [
        f"{item.program.institution_zh or item.program.institution} {item.program.name_zh or item.program.name}："
        f"{item.risks[0] if item.risks else '方向或硬条件不适合当前方案。'}"
        for item in matches
        if item.tier == "not_recommended"
    ][:6]
    next_actions = [
        "先确认目标方向是否以 CS/AI/Data 为主，避免商科弱相关项目挤占申请名额。",
        "上传成绩单或填写核心课程成绩后，重新计算课程匹配和先修课风险。",
        "对建议申请名单刷新学校官网信息，优先找到项目详情页、申请系统和 PDF/FAQ。",
        "把选定 6-10 个项目加入申请方案，再生成任务与材料时间线。",
    ]
    if assessment.decision_field_coverage < 70:
        next_actions.insert(1, "当前关键决策字段覆盖不足，正式定校前需要补充排名、课程、经历深度和语言单项。")
    return ConsultantSchoolPlan(
        title="港新硕士择校方案初版",
        profile_summary=profile_summary,
        strategy_summary=strategy_summary,
        data_disclaimer=data_disclaimer,
        band_counts=band_counts,
        items=items,
        rejected_or_deferred=deferred,
        next_actions=next_actions[:6],
    )


def _consultant_item(item) -> ConsultantPlanItem:
    band = {
        "reach": "冲刺",
        "target": "主申",
        "safe": "保底",
        "candidate": "候选",
        "blocked": "暂不建议",
    }[item.strategy_band]
    explanation = item.explanation
    fit_parts = []
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
    student_fit = "；".join(fit_parts) or "等待背景字段补充后判断。"
    main_risk = item.risks[0] if item.risks else "未发现明显风险，但仍需打开学校官网确认。"
    next_action = item.actions[0] if item.actions else "打开学校官网详情页，确认当前申请季信息。"
    return ConsultantPlanItem(
        program_id=item.program.id,
        band=band,
        institution=item.program.institution_zh or item.program.institution,
        program_name=item.program.name_zh or item.program.name,
        why_this_band=item.consultant_note or "按背景竞争力、院校挑战度和方向匹配分入当前档位。",
        student_fit=student_fit,
        main_risk=main_risk,
        next_action=next_action,
        data_warning=item.source_warning or "当前申请季信息仍需学校官网确认。",
        official_url=item.program.official_program_url or item.program.source.url,
        application_url=item.program.application_url,
    )


def _student_direction_label(tags) -> str:
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
    visible = [labels.get(tag, str(tag).replace("_", " ")) for tag in tags]
    return " / ".join(visible[:4])
