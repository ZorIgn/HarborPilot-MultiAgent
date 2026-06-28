from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from harbor_agent.models import (
    AgentContract,
    AgentContractCheck,
    AgentSystemReport,
    AgentTraceEvent,
    AgentWorkflowContract,
)

AGENT_CONTRACTS: list[AgentContract] = [
    AgentContract(
        agent_name="ProfileAgent",
        responsibility="Normalize applicant form input, map discipline intent tags, and surface missing profile fields.",
        inputs=["ApplicantProfileInput"],
        outputs=["NormalizedProfile"],
        tools=["taxonomy_mapper", "profile_completeness"],
        deterministic_guardrails=["GPA scale normalization", "discipline taxonomy mapping"],
    ),
    AgentContract(
        agent_name="EvidenceAgent",
        responsibility="Assess fact readiness and recommend evidence uploads before profile claims are trusted.",
        inputs=["NormalizedProfile"],
        outputs=["EvidenceReview"],
        tools=["evidence_level_counter", "confirmation_queue"],
        upstream_agents=["ProfileAgent"],
        human_gate="Student evidence upload and confirmation queue",
        deterministic_guardrails=["Self-reported facts remain low confidence"],
    ),
    AgentContract(
        agent_name="EvaluationAgent",
        responsibility="Score profile readiness with deterministic rules and optional LLM wording only.",
        inputs=["NormalizedProfile"],
        outputs=["AssessmentResult"],
        tools=["rules.evaluate_general_profile"],
        upstream_agents=["ProfileAgent", "EvidenceAgent"],
        deterministic_guardrails=["Language tests are evaluated by exam type", "GPA is normalized before scoring"],
    ),
    AgentContract(
        agent_name="ProgramIntelligenceAgent",
        responsibility="Recall HK/SG programme candidates and attach source coverage metadata.",
        inputs=["NormalizedProfile", "Program catalog", "Source registry"],
        outputs=["Program candidates"],
        tools=["official_source_registry", "community_signal_recall", "program_catalog.recall"],
        upstream_agents=["EvaluationAgent"],
        deterministic_guardrails=["Community signals are never official requirements"],
    ),
    AgentContract(
        agent_name="SchoolMatchingAgent",
        responsibility="Apply hard-rule eligibility checks, intent alignment, and conservative application bands.",
        inputs=["NormalizedProfile", "AssessmentResult", "Program candidates"],
        outputs=["ProgramMatch list"],
        tools=["rules.check_program_eligibility", "matching_score_service"],
        upstream_agents=["ProgramIntelligenceAgent"],
        deterministic_guardrails=["Strict CS/AI/Data intent blocks off-direction business programmes", "Unverified data cannot become a formal recommendation"],
    ),
    AgentContract(
        agent_name="DataRefreshAgent",
        responsibility="Check public source freshness, robots policy, snapshots, page hashes, and field extraction candidates.",
        inputs=["DataRefreshRequest", "Source registry"],
        outputs=["DataRefreshReport"],
        tools=["source_registry.lookup", "robots_policy_check", "snapshot_hash", "field_review_queue"],
        upstream_agents=["SchoolMatchingAgent"],
        human_gate="Official-field review queue",
        deterministic_guardrails=["robots.txt is checked before live fetch", "Fetched fields default to review_required"],
    ),
    AgentContract(
        agent_name="ProgramDataAcquisitionAgent",
        responsibility="Build programme data packages combining official requirements, content sections, timelines, and public community experience plans.",
        inputs=["DataAcquisitionRequest", "Program catalog", "Acquisition source config"],
        outputs=["DataAcquisitionReport"],
        tools=["SourceDiscoveryAgent", "OfficialCrawlerAgent", "CommunitySignalAgent", "HumanReviewGateAgent"],
        human_gate="Official fields can publish only after review",
        deterministic_guardrails=["Community experience is reference only"],
    ),

    AgentContract(
        agent_name="SourceCrawlQueueAgent",
        responsibility="Turn official and public-community acquisition plans into deterministic crawler jobs with robots, snapshot, parser, and human-review boundaries.",
        inputs=["CrawlQueueRequest", "DataAcquisitionReport"],
        outputs=["CrawlQueueReport"],
        tools=["crawl_job_builder", "robots_policy_gate", "snapshot_policy_gate", "community_boundary_gate"],
        upstream_agents=["ProgramDataAcquisitionAgent"],
        human_gate="Crawler jobs only produce review candidates; they cannot publish official fields.",
        deterministic_guardrails=["Official and community jobs are separated", "Community jobs cannot emit official fields"],
    ),
    AgentContract(
        agent_name="TimelineAgent",
        responsibility="Generate preparation tasks without treating unverified deadlines as official back-planning anchors.",
        inputs=["Selected ProgramMatch list"],
        outputs=["TimelineTask list"],
        tools=["deadline_backplanner", "shared_task_merger"],
        upstream_agents=["DataRefreshAgent"],
        human_gate="Deadline confirmation before formal schedule",
        deterministic_guardrails=["No official back-plan for unverified deadlines"],
    ),
    AgentContract(
        agent_name="StoryCardAgent",
        responsibility="Convert questionnaire answers into structured experience story cards.",
        inputs=["QuestionnaireResponse"],
        outputs=["StoryCard list"],
        tools=["questionnaire_gap_check", "star_story_builder"],
        human_gate="Student confirms factual story details",
    ),
    AgentContract(
        agent_name="WritingAgent",
        responsibility="Draft writing plans with fact bindings and programme-specific cautions.",
        inputs=["NormalizedProfile", "Selected ProgramMatch list", "StoryCard list"],
        outputs=["WritingDraft"],
        tools=["fact_binding_builder", "outline_planner"],
        upstream_agents=["StoryCardAgent"],
        human_gate="Sentence-level fact verification before export",
        deterministic_guardrails=["Unsupported claims become review flags"],
    ),

    AgentContract(
        agent_name="ScenarioAuditAgent",
        responsibility="Run simulated applicant and target-program drilldown audits that fail on unreasonable recommendations, missing evidence gates, or source-boundary leaks.",
        inputs=["ProgramPlanResult", "ApplicationPlanResult", "CrawlQueueReport", "DataAcquisitionReport", "ReviewQueueSummary"],
        outputs=["ScenarioAuditReport"],
        tools=["scenario_matrix", "target_program_drilldown", "data_trust_gate", "agent_trace_gate"],
        upstream_agents=["SchoolMatchingAgent", "ProgramDataAcquisitionAgent", "SourceCrawlQueueAgent", "ReviewAgent"],
        human_gate="Failed audit findings must be reviewed before demo claims are treated as product behavior.",
        deterministic_guardrails=[
            "Target-program drilldowns must include data packages and review queues",
            "Scenario audits fail when unverified fields become formal recommendations",
            "Community sources cannot leak official requirement fields",
        ],
    ),
    AgentContract(
        agent_name="ReviewAgent",
        responsibility="Final gate for hard-rule violations, unverified programme data, timeline gates, and writing risks.",
        inputs=["ProgramMatch list", "WritingDraft"],
        outputs=["Review gate result"],
        tools=["official_field_gate", "timeline_gate", "fact_binding_gate"],
        upstream_agents=["TimelineAgent", "WritingAgent"],
        human_gate="Blocks formal use until official fields and student facts are confirmed",
        deterministic_guardrails=["Unverified source fields set passed=false"],
    ),
]

WORKFLOW_CONTRACTS: list[AgentWorkflowContract] = [
    AgentWorkflowContract(
        workflow_name="assessment",
        required_agents=[
            "ProfileAgent",
            "EvidenceAgent",
            "EvaluationAgent",
            "ProgramIntelligenceAgent",
            "SchoolMatchingAgent",
            "TimelineAgent",
            "WritingAgent",
            "ReviewAgent",
        ],
        terminal_agent="ReviewAgent",
        human_gate_required=True,
    ),
    AgentWorkflowContract(
        workflow_name="program_plan",
        required_agents=[
            "ProfileAgent",
            "EvidenceAgent",
            "EvaluationAgent",
            "ProgramIntelligenceAgent",
            "SchoolMatchingAgent",
        ],
        terminal_agent="SchoolMatchingAgent",
        human_gate_required=True,
    ),
    AgentWorkflowContract(
        workflow_name="application_plan",
        required_agents=[
            "ProfileAgent",
            "EvidenceAgent",
            "EvaluationAgent",
            "ProgramIntelligenceAgent",
            "SchoolMatchingAgent",
            "DataRefreshAgent",
            "ProgramIntelligenceAgent",
            "TimelineAgent",
            "ReviewAgent",
        ],
        terminal_agent="ReviewAgent",
        human_gate_required=True,
    ),
    AgentWorkflowContract(
        workflow_name="writing_plan",
        required_agents=[
            "ProfileAgent",
            "EvidenceAgent",
            "EvaluationAgent",
            "ProgramIntelligenceAgent",
            "SchoolMatchingAgent",
            "StoryCardAgent",
            "WritingAgent",
            "ReviewAgent",
        ],
        terminal_agent="ReviewAgent",
        human_gate_required=True,
    ),


    AgentWorkflowContract(
        workflow_name="scenario_audit",
        required_agents=[
            "ProfileAgent",
            "EvidenceAgent",
            "EvaluationAgent",
            "ProgramIntelligenceAgent",
            "SchoolMatchingAgent",
            "ProgramDataAcquisitionAgent",
            "SourceCrawlQueueAgent",
            "ReviewAgent",
            "ScenarioAuditAgent",
        ],
        terminal_agent="ScenarioAuditAgent",
        human_gate_required=True,
    ),
    AgentWorkflowContract(
        workflow_name="crawl_queue",
        required_agents=["ProgramDataAcquisitionAgent", "SourceCrawlQueueAgent"],
        terminal_agent="SourceCrawlQueueAgent",
        human_gate_required=True,
    ),
    AgentWorkflowContract(
        workflow_name="data_acquisition",
        required_agents=["ProgramDataAcquisitionAgent"],
        terminal_agent="ProgramDataAcquisitionAgent",
        human_gate_required=True,
    ),
]


def build_agent_system_report() -> AgentSystemReport:
    checks = _contract_checks()
    return AgentSystemReport(
        generated_at=datetime.now(UTC),
        agents=AGENT_CONTRACTS,
        workflows=WORKFLOW_CONTRACTS,
        checks=checks,
        human_gates=sorted({contract.human_gate for contract in AGENT_CONTRACTS if contract.human_gate}),
        deterministic_guardrails=sorted(
            {guardrail for contract in AGENT_CONTRACTS for guardrail in contract.deterministic_guardrails}
        ),
    )


def validate_trace(workflow_name: str, trace: list[AgentTraceEvent]) -> list[AgentContractCheck]:
    workflow = next((item for item in WORKFLOW_CONTRACTS if item.workflow_name == workflow_name), None)
    if workflow is None:
        return [AgentContractCheck(check_id="workflow_known", passed=False, detail=f"Unknown workflow: {workflow_name}")]
    nodes = [event.node for event in trace]
    checks = [
        AgentContractCheck(
            check_id=f"{workflow_name}.required_order",
            passed=_contains_in_order(nodes, workflow.required_agents),
            detail=f"expected order={workflow.required_agents}; actual={nodes}",
        ),
        AgentContractCheck(
            check_id=f"{workflow_name}.terminal_agent",
            passed=bool(nodes) and nodes[-1] == workflow.terminal_agent,
            detail=f"expected terminal={workflow.terminal_agent}; actual={nodes[-1] if nodes else 'none'}",
        ),
        AgentContractCheck(
            check_id=f"{workflow_name}.tool_calls_present",
            passed=all(event.tool_calls for event in trace),
            detail="every trace event should expose the tools/contracts it used",
        ),
    ]
    if workflow.human_gate_required:
        checks.append(
            AgentContractCheck(
                check_id=f"{workflow_name}.human_gate_visible",
                passed=any("gate" in " ".join(event.tool_calls).lower() or "review" in event.node.lower() for event in trace),
                detail="workflow should surface at least one review or human gate",
            )
        )
    return checks


def _contract_checks() -> list[AgentContractCheck]:
    names = [contract.agent_name for contract in AGENT_CONTRACTS]
    agent_dir = Path(__file__).resolve().parents[1] / "agents"
    expected_files = {
        "ProfileAgent": "profile.py",
        "EvidenceAgent": "evidence.py",
        "EvaluationAgent": "evaluation.py",
        "ProgramIntelligenceAgent": "program_intelligence.py",
        "SchoolMatchingAgent": "matching.py",
        "DataRefreshAgent": "data_refresh.py",
        "ProgramDataAcquisitionAgent": "data_acquisition.py",
        "SourceCrawlQueueAgent": "source_crawl_queue.py",
        "TimelineAgent": "timeline.py",
        "StoryCardAgent": "story_card.py",
        "WritingAgent": "writing.py",
        "ReviewAgent": "review.py",
        "ScenarioAuditAgent": "scenario_audit.py",
    }
    checks = [
        AgentContractCheck(
            check_id="agent_names_unique",
            passed=len(names) == len(set(names)),
            detail=f"registered={len(names)} unique={len(set(names))}",
        ),
        AgentContractCheck(
            check_id="human_gates_present",
            passed=sum(1 for contract in AGENT_CONTRACTS if contract.human_gate) >= 5,
            detail="high-risk workflows need explicit human gates",
        ),
        AgentContractCheck(
            check_id="guardrails_present",
            passed=sum(len(contract.deterministic_guardrails) for contract in AGENT_CONTRACTS) >= 8,
            detail="critical admissions decisions must include deterministic guardrails",
        ),
    ]
    for agent_name, file_name in expected_files.items():
        checks.append(
            AgentContractCheck(
                check_id=f"agent_file.{agent_name}",
                passed=(agent_dir / file_name).exists(),
                detail=f"expected {file_name}",
            )
        )
    for workflow in WORKFLOW_CONTRACTS:
        missing = [agent for agent in workflow.required_agents if agent not in names]
        checks.append(
            AgentContractCheck(
                check_id=f"workflow_agents.{workflow.workflow_name}",
                passed=not missing,
                detail=f"missing={missing}",
            )
        )
    return checks


def _contains_in_order(actual: list[str], expected: list[str]) -> bool:
    position = 0
    for node in actual:
        if position < len(expected) and node == expected[position]:
            position += 1
    return position == len(expected)