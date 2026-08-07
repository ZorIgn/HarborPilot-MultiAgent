from __future__ import annotations

from pydantic import BaseModel, Field

from harbor_agent.policies.source_policy import ensure_safe_https_url
from harbor_agent.runtime.errors import HumanReviewRequired
from harbor_agent.runtime.state import AgentState
from harbor_agent.services.data_loader import load_programs
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
    field_names: list[str] = Field(default_factory=list)
    requires_human_review: bool = True


class SourceCrawlPlan(BaseModel):
    program_ids: list[str] = Field(default_factory=list)
    official_urls: list[str] = Field(default_factory=list)


def _discover(_: AgentState, args: ProgramSourceInput) -> SourceDiscoveryResult:
    program = next((item for item in load_programs() if item.id == args.program_id), None)
    if program is None:
        return SourceDiscoveryResult(program_id=args.program_id)
    urls = [str(value) for value in (program.official_program_url, program.application_url, program.source.url) if value]
    return SourceDiscoveryResult(program_id=args.program_id, official_urls=list(dict.fromkeys(urls)))


def _snapshot(_: AgentState, args: SnapshotSourceInput) -> SnapshotResultOutput:
    url = ensure_safe_https_url(args.url)
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


def _binding(_: AgentState, args: SourceBindingProposal) -> SourceBindingProposal:
    # Publication/binding can change official evidence and therefore must be
    # approved by a human. The tool only returns a typed review proposal.
    return args


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
        ToolDefinition("bind_source_to_program", "Create a human-review proposal to bind source evidence to a programme.", SourceBindingProposal, SourceBindingProposal, _binding, requires_human_review=True),
        ToolDefinition("build_source_crawl_plan", "Build deterministic official-source crawl jobs for selected programmes.", EmptyToolInput, SourceCrawlPlan, _plan),
    ]
