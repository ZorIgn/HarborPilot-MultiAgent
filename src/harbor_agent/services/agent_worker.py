from __future__ import annotations

import time
from typing import Any

from harbor_agent.services.catalog_auto_update import CatalogAutoUpdateService
from harbor_agent.services.data_acquisition import ProgramDataAcquisitionService
from harbor_agent.agents.orchestrator import WorkflowOrchestrator
from harbor_agent.services.source_crawl_queue import SourceCrawlQueueService
from harbor_agent.config import get_settings
from harbor_agent.core.llm import build_llm_provider
from harbor_agent.models import (
    ApplicantProfileInput,
    CatalogAutoUpdateRequest,
    CrawlQueueRequest,
    DataAcquisitionRequest,
)
from harbor_agent.services.agent_runtime import claim_next_agent_job, complete_agent_job
from harbor_agent.services.profile_store import load_profile
from harbor_agent.services.scenario_audit_runner import scenario_audit_summary


def execute_agent_job(job: dict[str, Any], llm_provider: Any | None = None) -> dict[str, Any]:
    """Execute one claimed agent job and persist the terminal status.

    The worker intentionally writes only to the agent runtime and review queues. Student-facing
    programme fields are still published through the human review gate.
    """

    job_id = str(job["job_id"])
    workflow_name = str(job["workflow_name"])
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    provider = llm_provider or build_llm_provider(get_settings())
    orchestrator = WorkflowOrchestrator(provider)
    try:
        if workflow_name == "program_plan":
            profile = ApplicantProfileInput.model_validate(payload.get("profile") or load_profile())
            result = orchestrator.run_program_plan_stage(profile)
            summary = f"program_plan workflow={result.workflow_id}"
            complete_agent_job(job_id, "COMPLETED", summary)
            return {"ok": True, "job_id": job_id, "status": "COMPLETED", "summary": summary}
        if workflow_name == "application_plan":
            profile = ApplicantProfileInput.model_validate(payload.get("profile") or load_profile())
            selected_ids = list(payload.get("selected_program_ids") or [])
            result = orchestrator.run_application_plan_stage(profile, selected_ids)
            summary = f"application_plan workflow={result.workflow_id}; tasks={len(result.timeline)}"
            complete_agent_job(job_id, "COMPLETED", summary)
            return {"ok": True, "job_id": job_id, "status": "COMPLETED", "summary": summary}
        if workflow_name == "data_acquisition":
            result = ProgramDataAcquisitionService().run(DataAcquisitionRequest.model_validate(payload))
            summary = f"data_acquisition packages={len(result.packages)}"
            complete_agent_job(job_id, "COMPLETED", summary)
            return {"ok": True, "job_id": job_id, "status": "COMPLETED", "summary": summary}
        if workflow_name == "crawl_queue":
            result = SourceCrawlQueueService().run(CrawlQueueRequest.model_validate(payload))
            summary = f"crawl_queue jobs={result.job_count}"
            complete_agent_job(job_id, "COMPLETED", summary)
            return {"ok": True, "job_id": job_id, "status": "COMPLETED", "summary": summary}
        if workflow_name == "catalog_auto_update":
            result = CatalogAutoUpdateService().run(CatalogAutoUpdateRequest.model_validate(payload))
            summary = f"catalog_auto_update candidates={result.candidate_count}"
            complete_agent_job(job_id, "COMPLETED", summary)
            return {"ok": True, "job_id": job_id, "status": "COMPLETED", "summary": summary}
        if workflow_name == "scenario_audit":
            result = scenario_audit_summary()
            summary = f"scenario_audit failures={result.get('failure_count')}"
            complete_agent_job(job_id, "COMPLETED", summary)
            return {"ok": True, "job_id": job_id, "status": "COMPLETED", "summary": summary}
        if workflow_name.startswith("retry:"):
            summary = "Retry queued for operator review; resolve the handoff after checking inputs."
            complete_agent_job(job_id, "NEEDS_HUMAN", summary)
            return {"ok": False, "job_id": job_id, "status": "NEEDS_HUMAN", "summary": summary}
        summary = f"Unsupported workflow for local worker: {workflow_name}"
        complete_agent_job(job_id, "NEEDS_HUMAN", summary)
        return {"ok": False, "job_id": job_id, "status": "NEEDS_HUMAN", "summary": summary}
    except Exception as exc:  # pragma: no cover - exact failing agent varies by environment
        summary = f"{type(exc).__name__}: {exc}"
        complete_agent_job(job_id, "FAILED", summary)
        return {"ok": False, "job_id": job_id, "status": "FAILED", "summary": summary}


def run_next_agent_job(*, assigned_to: str = "local_agent_worker", llm_provider: Any | None = None) -> dict[str, Any]:
    job = claim_next_agent_job(assigned_to=assigned_to)
    if job is None:
        return {"ok": True, "message": "No queued agent job is waiting.", "job": None, "result": None}
    result = execute_agent_job(job, llm_provider=llm_provider)
    return {"ok": bool(result.get("ok")), "message": result.get("summary", "Agent job processed."), "job": job, "result": result}


def run_agent_worker_loop(
    *,
    max_jobs: int = 20,
    poll_interval_seconds: float = 0.0,
    assigned_to: str = "local_agent_worker",
    llm_provider: Any | None = None,
) -> dict[str, Any]:
    max_jobs = max(1, int(max_jobs))
    processed: list[dict[str, Any]] = []
    empty_polls = 0
    while len(processed) < max_jobs:
        outcome = run_next_agent_job(assigned_to=assigned_to, llm_provider=llm_provider)
        if outcome.get("job") is None:
            empty_polls += 1
            break
        processed.append(outcome)
        if poll_interval_seconds > 0 and len(processed) < max_jobs:
            time.sleep(poll_interval_seconds)
    statuses = [str(item.get("result", {}).get("status", "UNKNOWN")) for item in processed]
    return {
        "processed_count": len(processed),
        "empty_polls": empty_polls,
        "completed_count": statuses.count("COMPLETED"),
        "failed_count": statuses.count("FAILED"),
        "needs_human_count": statuses.count("NEEDS_HUMAN"),
        "jobs": processed,
    }
