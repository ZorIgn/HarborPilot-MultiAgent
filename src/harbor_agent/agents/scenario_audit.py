from __future__ import annotations

from dataclasses import dataclass, field

from harbor_agent.models import (
    ApplicationPlanResult,
    CrawlQueueReport,
    DataAcquisitionReport,
    DataStatus,
    ProgramPlanResult,
    ReviewQueueSummary,
    SourceTrustLevel,
)


@dataclass(frozen=True)
class ScenarioAuditExpectation:
    """Quality expectations for a simulated applicant scenario."""

    name: str
    expect_strict_intent: bool = False
    expect_no_reach: bool = False
    expected_mix_min: int = 6
    expected_mix_max: int = 10
    blocked_terms: set[str] = field(default_factory=set)
    target_program_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScenarioAuditReport:
    agent_name: str
    scenario_name: str
    failures: list[str]
    checked_target_program_ids: tuple[str, ...]
    guardrails: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failures


class ScenarioAuditAgent:
    """Runs deterministic self-audit gates over simulated admissions workflows."""

    name = "ScenarioAuditAgent"
    guardrails = (
        "unverified data cannot produce formal recommendations",
        "official deadlines cannot drive back-planning unless verified",
        "strict CS/AI/Data intent must stay on core programme categories",
        "community sources cannot emit official requirement fields",
        "target programme drilldowns need data packages and review queues",
    )

    def run(
        self,
        expectation: ScenarioAuditExpectation,
        plan: ProgramPlanResult,
        application: ApplicationPlanResult,
        crawl_queue: CrawlQueueReport,
        data_acquisition: DataAcquisitionReport,
        review_queues: dict[str, ReviewQueueSummary],
    ) -> ScenarioAuditReport:
        failures: list[str] = []
        self._check_plan(expectation, plan, failures)
        self._check_application(application, failures)
        self._check_crawl_queue(crawl_queue, failures)
        self._check_target_programs(expectation, plan, data_acquisition, review_queues, failures)
        return ScenarioAuditReport(
            agent_name=self.name,
            scenario_name=expectation.name,
            failures=failures,
            checked_target_program_ids=expectation.target_program_ids,
            guardrails=self.guardrails,
        )

    def _check_plan(self, expectation: ScenarioAuditExpectation, plan: ProgramPlanResult, failures: list[str]) -> None:
        if plan.intent_profile is None:
            failures.append("missing intent profile")
        elif plan.intent_profile.strict_intent is not expectation.expect_strict_intent:
            failures.append(
                f"strict intent expected {expectation.expect_strict_intent}, got {plan.intent_profile.strict_intent}"
            )

        if not (expectation.expected_mix_min <= len(plan.application_mix) <= expectation.expected_mix_max):
            failures.append(
                f"application mix size expected {expectation.expected_mix_min}-{expectation.expected_mix_max}, "
                f"got {len(plan.application_mix)}"
            )
        if not plan.application_mix:
            failures.append("empty application mix")

        if any(item.formal_recommendation for item in plan.application_mix):
            failures.append("unverified catalog produced formal recommendations")

        if expectation.expect_no_reach:
            reach_count = sum(1 for item in plan.application_mix if item.strategy_band == "reach")
            if reach_count:
                failures.append(f"regular-background conservative case has {reach_count} reach items")

        if expectation.blocked_terms:
            names = " ".join(
                f"{item.program.name} {item.program.name_zh or ''} {' '.join(item.program.discipline_tags)}".lower()
                for item in plan.application_mix[:8]
            )
            bad_terms = sorted(term for term in expectation.blocked_terms if term in names)
            if bad_terms:
                failures.append(f"off-direction terms in top mix: {', '.join(bad_terms)}")

        if expectation.expect_strict_intent and any(item.match_category != "core" for item in plan.application_mix):
            failures.append("strict CS/AI/Data case contains non-core application mix items")

        required_trace = [
            "ProfileAgent",
            "EvidenceAgent",
            "EvaluationAgent",
            "ProgramIntelligenceAgent",
            "SchoolMatchingAgent",
        ]
        trace_nodes = [event.node for event in plan.trace]
        if trace_nodes[: len(required_trace)] != required_trace:
            failures.append(f"unexpected plan agent trace: {trace_nodes}")

    def _check_application(self, application: ApplicationPlanResult, failures: list[str]) -> None:
        if application.review.get("passed") is not False:
            failures.append("application review should remain blocked until official fields are verified")

        official_backplan = [
            task
            for task in application.timeline
            if task.date_basis == "official_deadline_backplan" and task.official_deadline != "NOT_PUBLISHED"
        ]
        official_deadline_backplan_label = "\u5b98\u65b9\u622a\u6b62\u5012\u63a8"
        official_backplan.extend(
            task
            for task in application.timeline
            if task.date_basis == official_deadline_backplan_label and task.official_deadline != "NOT_PUBLISHED"
        )
        if official_backplan:
            failures.append("unverified deadlines produced official back-planning tasks")

    def _check_crawl_queue(self, crawl_queue: CrawlQueueReport, failures: list[str]) -> None:
        if crawl_queue.job_count == 0:
            failures.append("crawl queue is empty for selected programs")
        if crawl_queue.official_job_count == 0:
            failures.append("crawl queue has no official-source jobs")
        if crawl_queue.community_job_count == 0:
            failures.append("crawl queue has no community-reference jobs")
        if not all(item.snapshot_required and item.human_review_required for item in crawl_queue.items):
            failures.append("crawl queue contains jobs without snapshot or human-review gates")

        official_only = {"deadline", "tuition_hkd", "language_requirement", "materials", "application_url", "essay_prompts"}
        community_leaks = [
            item.source_id
            for item in crawl_queue.items
            if item.trust_level == SourceTrustLevel.community and official_only & set(item.allowed_fields)
        ]
        if community_leaks:
            failures.append(f"community crawl jobs can emit official fields: {community_leaks}")

        if "SourceCrawlQueueAgent" not in crawl_queue.agent_chain:
            failures.append(f"crawl queue agent chain missing SourceCrawlQueueAgent: {crawl_queue.agent_chain}")

    def _check_target_programs(
        self,
        expectation: ScenarioAuditExpectation,
        plan: ProgramPlanResult,
        data_acquisition: DataAcquisitionReport,
        review_queues: dict[str, ReviewQueueSummary],
        failures: list[str],
    ) -> None:
        if not expectation.target_program_ids:
            failures.append("scenario has no target program drilldown ids")
            return

        by_program_id = {item.program.id: item for item in plan.recommendations}
        package_by_id = {package.program_id: package for package in data_acquisition.packages}
        official_fields = {"deadline", "tuition_hkd", "language_requirement", "materials", "application_url", "essay_prompts"}

        for program_id in expectation.target_program_ids:
            match = by_program_id.get(program_id)
            if match is None:
                failures.append(f"target program missing from recommendations: {program_id}")
                continue
            if match.formal_recommendation:
                failures.append(f"target program became formal without verified data: {program_id}")
            if not match.reasons or not match.risks or not match.actions:
                failures.append(f"target program lacks reasons/risks/actions: {program_id}")
            if not match.source_warning:
                failures.append(f"target program lacks source warning: {program_id}")
            if match.program.source.field_coverage == "complete" and match.program.data_status != DataStatus.verified:
                failures.append(f"target program claims complete coverage without VERIFIED status: {program_id}")
            if expectation.expect_strict_intent and match.match_category != "core":
                failures.append(f"strict-intent target is not core: {program_id} -> {match.match_category}")

            package = package_by_id.get(program_id)
            if package is None:
                failures.append(f"missing data package for target program: {program_id}")
                continue
            if package.production_ready:
                failures.append(f"unreviewed target package is production_ready: {program_id}")
            if not package.human_review_required:
                failures.append(f"target package does not require human review: {program_id}")
            coverage_fields = {item.field_name for item in package.coverage_items}
            missing_fields = sorted(official_fields - coverage_fields)
            if missing_fields:
                failures.append(f"target package missing coverage fields for {program_id}: {missing_fields}")
            if any(not item.blocks_formal_use for item in package.coverage_items if item.field_name in official_fields):
                failures.append(f"target package allows formal use before official verification: {program_id}")
            if not any(plan_item.trust_level == SourceTrustLevel.official for plan_item in package.acquisition_plan):
                failures.append(f"target package lacks official acquisition source: {program_id}")
            if not any(plan_item.trust_level == SourceTrustLevel.community for plan_item in package.acquisition_plan):
                failures.append(f"target package lacks public community/reference source: {program_id}")
            for plan_item in package.acquisition_plan:
                if plan_item.trust_level == SourceTrustLevel.community and official_fields & set(plan_item.allowed_fields):
                    failures.append(f"target community acquisition leaks official fields: {program_id}/{plan_item.source_id}")

            queue = review_queues.get(program_id)
            if queue is None:
                failures.append(f"missing review queue for target program: {program_id}")
                continue
            if queue.pending_count == 0:
                failures.append(f"review queue is empty for target program: {program_id}")
            for item in queue.items:
                if item.publishable:
                    if not item.source_type.startswith("official"):
                        failures.append(f"publishable review item is not official: {program_id}/{item.field_name}")
                    if not item.source_url or not item.evidence_snippet or not item.page_hash:
                        failures.append(f"publishable review item lacks source/snippet/hash: {program_id}/{item.field_name}")
