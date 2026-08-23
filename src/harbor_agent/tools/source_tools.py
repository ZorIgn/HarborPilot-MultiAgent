from __future__ import annotations

from pydantic import BaseModel, Field

from harbor_agent.policies.source_policy import ensure_safe_https_url
from harbor_agent.runtime.errors import HumanReviewRequired
from harbor_agent.runtime.state import AgentState
from harbor_agent.services.data_loader import load_programs
from harbor_agent.services.source_binding_store import save_program_source_binding
from harbor_agent.services.source_identity import (
    is_allowed_official_url,
    same_official_institution,
)
from harbor_agent.services.source_snapshot import snapshot_source
from harbor_agent.tools.base import ToolDefinition


class ProgramSourceInput(BaseModel):
    program_id: str


class SnapshotSourceInput(BaseModel):
    program_id: str | None = None
    url: str
    dry_run: bool = True


class SourceDiscoveryResult(BaseModel):
    program_id: str
    official_urls: list[str] = Field(default_factory=list)


class SnapshotResultOutput(BaseModel):
    program_id: str | None = None
    url: str
    final_url: str | None = None
    status: str
    ok: bool
    page_hash: str | None = None
    snapshot_id: str | None = None
    excerpt: str = ""
    content_bytes: int = 0


class SourceBindingProposal(BaseModel):
    program_id: str
    source_url: str
    field_names: list[str] = Field(min_length=1)


class SourceBindingResult(BaseModel):
    binding_id: str
    workflow_id: str
    program_id: str
    source_url: str
    field_names: list[str]
    page_hash: str | None = None
    approval_id: str
    reviewer_id: str
    created_at: str
    persisted: bool


class SourceCrawlPlan(BaseModel):
    program_ids: list[str] = Field(default_factory=list)
    official_urls: list[str] = Field(default_factory=list)


def _discover(_: AgentState, args: ProgramSourceInput) -> SourceDiscoveryResult:
    program = next((item for item in load_programs() if item.id == args.program_id), None)
    if program is None:
        return SourceDiscoveryResult(program_id=args.program_id)
    urls = [str(value) for value in (program.official_program_url, program.application_url, program.source.url) if value]
    return SourceDiscoveryResult(program_id=args.program_id, official_urls=list(dict.fromkeys(urls)))


def _snapshot(state: AgentState, args: SnapshotSourceInput) -> SnapshotResultOutput:
    url = ensure_safe_https_url(args.url)
    if not args.dry_run and not state.working_memory.get("verification_source_fetch_enabled"):
        raise PermissionError(
            "live source snapshots require a runtime request with explicit real/hybrid mode, programme scope and server-issued operator authorization"
        )
    result = snapshot_source(url, dry_run=args.dry_run)
    return SnapshotResultOutput(
        program_id=args.program_id,
        url=result.url,
        final_url=result.final_url,
        status=result.status,
        ok=result.ok,
        page_hash=result.page_hash,
        snapshot_id=result.snapshot_path,
        excerpt=result.text[:1200],
        content_bytes=result.content_bytes,
    )


def _binding(state: AgentState, args: SourceBindingProposal) -> SourceBindingResult:
    approval = state.active_tool_approval
    if approval is None or approval.tool_name != "bind_source_to_program" or not approval.reviewer_id:
        raise HumanReviewRequired("source binding requires an active exact approval")
    # Binding does not perform a network request.  The URL was already fetched
    # through snapshot_official_source's SSRF gateway; re-running DNS policy
    # here would make an auditable stored snapshot depend on later DNS answers.
    source_url = args.source_url.strip()
    program = next((item for item in load_programs() if item.id == args.program_id), None)
    if program is None:
        raise ValueError(f"unknown program_id: {args.program_id}")
    expected_url = str(program.official_program_url or program.source.url or "")
    if not is_allowed_official_url(source_url) or not same_official_institution(source_url, expected_url):
        raise ValueError("source binding must use the programme institution's official HTTPS domain")
    tool_results = state.working_memory.get("tool_results", {})
    extraction = tool_results.get("extract_program_fields", {}) if isinstance(tool_results, dict) else {}
    if (
        not isinstance(extraction, dict)
        or extraction.get("program_id") != args.program_id
        or extraction.get("source_url") != source_url
    ):
        raise ValueError("source binding requires the current programme extraction result")
    candidates = extraction.get("fields", [])
    extracted_names = {
        str(item.get("field_name"))
        for item in candidates
        if isinstance(item, dict) and item.get("field_name")
    }
    if not set(args.field_names).issubset(extracted_names):
        raise ValueError("source binding fields must come from the current extraction session")
    snapshot = tool_results.get("snapshot_official_source", {}) if isinstance(tool_results, dict) else {}
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("program_id") != args.program_id
        or snapshot.get("url") != source_url
        or not snapshot.get("ok")
    ):
        raise ValueError("source binding requires the successful current programme snapshot")
    page_hash = snapshot.get("page_hash") if isinstance(snapshot, dict) else None
    persisted = save_program_source_binding(
        workflow_id=state.workflow_id,
        program_id=args.program_id,
        source_url=source_url,
        field_names=args.field_names,
        page_hash=str(page_hash) if page_hash else None,
        approval_id=approval.approval_id,
        reviewer_id=approval.reviewer_id,
    )
    return SourceBindingResult.model_validate(persisted)


def _plan(state: AgentState, _: BaseModel) -> SourceCrawlPlan:
    ids = state.selected_program_ids or state.candidate_program_ids[:12]
    selected = {item.id: item for item in load_programs() if item.id in ids}
    urls = [str(program.official_program_url or program.source.url) for program in selected.values() if program.official_program_url or program.source.url]
    return SourceCrawlPlan(program_ids=list(selected), official_urls=urls)


def definitions() -> list[ToolDefinition]:
    from harbor_agent.tools.base import EmptyToolInput

    return [
        ToolDefinition("discover_official_sources", "Discover official programme and application URLs from the catalogue.", ProgramSourceInput, SourceDiscoveryResult, _discover),
        ToolDefinition("snapshot_official_source", "Fetch an HTTPS official source through the shared SSRF/robots safety gateway.", SnapshotSourceInput, SnapshotResultOutput, _snapshot, max_retries=3, retryable=True),
        ToolDefinition("bind_source_to_program", "Persist one exact, human-approved official source binding.", SourceBindingProposal, SourceBindingResult, _binding, requires_human_review=True),
        ToolDefinition("build_source_crawl_plan", "Build deterministic official-source crawl jobs for selected programmes.", EmptyToolInput, SourceCrawlPlan, _plan),
    ]
