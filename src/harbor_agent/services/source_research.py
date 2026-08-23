"""Deterministic, bounded planning for official programme-source research.

This module deliberately stops at a *plan*.  It does not fetch pages, parse
requirements, bind a source to a programme, or publish any fact.  Those
operations remain owned by the Verification workflow and its human review
gate.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from harbor_agent.models import Program, SourcePolicy, SourceRegistry
from harbor_agent.services.program_urls import has_application_entry, has_program_detail_page
from harbor_agent.services.source_identity import is_allowed_official_url, official_institution_domain


OFFICIAL_FIELD_TARGETS = [
    "official_program_url",
    "deadline",
    "tuition_hkd",
    "min_gpa",
    "language_requirement",
    "required_backgrounds",
    "portfolio_required",
    "materials",
    "application_url",
    "essay_prompts",
]

_INDEX_FIELDS = ["official_program_url"]
_APPLICATION_FIELDS = [
    "application_url",
    "deadline",
    "min_gpa",
    "language_requirement",
    "required_backgrounds",
    "portfolio_required",
    "materials",
    "essay_prompts",
    "tuition_hkd",
]
_DETAIL_FIELDS = list(OFFICIAL_FIELD_TARGETS)


class SourceResearchLimits(BaseModel):
    """Hard limits included in every plan so a worker can enforce them."""

    max_programs: int = Field(default=12, ge=1, le=80)
    max_urls_per_program: int = Field(default=4, ge=1, le=12)
    max_total_urls: int = Field(default=48, ge=1, le=240)
    max_fields_per_program: int = Field(default=len(OFFICIAL_FIELD_TARGETS), ge=1, le=20)
    max_registry_sources_per_program: int = Field(default=3, ge=0, le=12)


class SourceResearchSource(BaseModel):
    """One allowlisted official URL proposed for later Verification work."""

    source_id: str
    url: str
    official_domain: str
    scope: str
    trust_level: str = "official"
    allowed_fields: list[str] = Field(default_factory=list)
    source_origin: str = "catalog"


class SourceResearchTarget(BaseModel):
    """Bounded source and field targets for one known catalogue programme."""

    program_id: str
    sources: list[SourceResearchSource] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    field_targets: list[str] = Field(default_factory=list)
    max_urls: int = Field(default=0, ge=0)
    stop_conditions: list[str] = Field(default_factory=list)


class SourceResearchPlan(BaseModel):
    """A serializable research plan, never a fact publication result."""

    plan_version: str = "source-research-v1"
    candidate_program_ids: list[str] = Field(default_factory=list)
    targets: list[SourceResearchTarget] = Field(default_factory=list)
    limits: SourceResearchLimits = Field(default_factory=SourceResearchLimits)
    total_url_count: int = Field(default=0, ge=0)
    publication_allowed: bool = False
    network_allowed: bool = False
    stop_conditions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def build_source_research_plan(
    candidate_program_ids: Iterable[str],
    *,
    programs: Iterable[Program],
    registry: SourceRegistry,
    limits: SourceResearchLimits | None = None,
) -> SourceResearchPlan:
    """Build a stable official-only plan from already-known catalogue data.

    Unknown candidate IDs are reported and skipped.  The planner never falls
    back to an unrelated catalogue slice: explicit candidate scope must remain
    explicit, and an empty/invalid scope yields an empty plan with warnings.
    """

    effective_limits = limits or SourceResearchLimits()
    by_id = {program.id: program for program in programs}
    requested_ids = list(dict.fromkeys(str(value) for value in candidate_program_ids if str(value).strip()))
    selected_ids = requested_ids[: effective_limits.max_programs]
    warnings: list[str] = []
    if len(requested_ids) > effective_limits.max_programs:
        warnings.append(
            f"candidate scope capped at {effective_limits.max_programs} programmes; remaining IDs were not planned"
        )

    targets: list[SourceResearchTarget] = []
    for program_id in selected_ids:
        program = by_id.get(program_id)
        if program is None:
            warnings.append(f"unknown catalogue programme skipped: {program_id}")
            continue
        target = _target_for_program(program, registry, effective_limits, warnings)
        targets.append(target)

    # Apply one global URL budget deterministically after the per-program cap.
    remaining = effective_limits.max_total_urls
    bounded_targets: list[SourceResearchTarget] = []
    for target in targets:
        sources = target.sources[:remaining]
        if len(sources) < len(target.sources):
            warnings.append(
                f"global URL budget reached while planning {target.program_id}; remaining sources were not planned"
            )
        bounded_targets.append(
            target.model_copy(
                update={
                    "sources": sources,
                    "allowed_domains": list(dict.fromkeys(source.official_domain for source in sources)),
                    "max_urls": len(sources),
                }
            )
        )
        remaining = max(0, remaining - len(sources))

    total_urls = sum(len(target.sources) for target in bounded_targets)
    return SourceResearchPlan(
        candidate_program_ids=[target.program_id for target in bounded_targets],
        targets=bounded_targets,
        limits=effective_limits,
        total_url_count=total_urls,
        publication_allowed=False,
        network_allowed=False,
        stop_conditions=[
            "stop after max_programs candidate programmes",
            "stop after max_urls_per_program official URLs per programme",
            "stop after max_total_urls across the plan",
            "stop when the bounded official field target set is scheduled",
            "do not add open-web, directory, community, or unallowlisted URLs",
        ],
        warnings=warnings,
    )


def _target_for_program(
    program: Program,
    registry: SourceRegistry,
    limits: SourceResearchLimits,
    warnings: list[str],
) -> SourceResearchTarget:
    expected_domains = _known_domains(program)
    candidates: list[SourceResearchSource] = []
    seen: set[tuple[str, str, str]] = set()

    def add_source(
        *,
        source_id: str,
        url: str | None,
        scope: str,
        fields: list[str],
        origin: str,
    ) -> None:
        normalized = _safe_official_url(url)
        if normalized is None:
            return
        domain = official_institution_domain(normalized)
        if domain is None or (expected_domains and domain not in expected_domains):
            return
        key = (source_id, normalized, scope)
        if key in seen:
            return
        seen.add(key)
        candidates.append(
            SourceResearchSource(
                source_id=source_id,
                url=normalized,
                official_domain=domain,
                scope=scope,
                trust_level="official",
                allowed_fields=list(dict.fromkeys(fields)),
                source_origin=origin,
            )
        )

    # Prefer a programme detail page and application system when the catalog
    # already knows one.  Generic index URLs remain discovery-only.
    detail_url = str(program.official_program_url) if program.official_program_url else None
    if detail_url and has_program_detail_page(program):
        add_source(
            source_id=f"program:{program.id}:detail",
            url=detail_url,
            scope="programme_detail",
            fields=_DETAIL_FIELDS,
            origin="catalog.program.official_program_url",
        )
    application_url = str(program.application_url) if program.application_url else None
    if application_url and has_application_entry(program):
        add_source(
            source_id=f"program:{program.id}:application",
            url=application_url,
            scope="application_portal",
            fields=_APPLICATION_FIELDS,
            origin="catalog.program.application_url",
        )
    source_url = str(program.source.url) if program.source.url else None
    add_source(
        source_id=f"program:{program.id}:index",
        url=source_url,
        scope="institution_index",
        fields=_INDEX_FIELDS,
        origin="catalog.program.source.url",
    )

    registry_candidates = [
        source
        for source in registry.sources
        if source.trust_level.value == "official"
        and str(source.region) in {program.country, "GLOBAL"}
        and _safe_official_url(str(source.url)) is not None
        and official_institution_domain(str(source.url)) in expected_domains
    ]
    registry_candidates.sort(key=lambda source: (_registry_priority(source), source.source_id, str(source.url)))
    registry_count = 0
    for source in registry_candidates:
        if registry_count >= limits.max_registry_sources_per_program:
            break
        scope, fields = _registry_scope_fields(source)
        before = len(candidates)
        add_source(
            source_id=source.source_id,
            url=str(source.url),
            scope=scope,
            fields=fields,
            origin="source_registry",
        )
        if len(candidates) > before:
            registry_count += 1

    candidates = candidates[: limits.max_urls_per_program]
    if not candidates:
        warnings.append(f"no allowlisted official source known for programme: {program.id}")

    return SourceResearchTarget(
        program_id=program.id,
        sources=candidates,
        allowed_domains=list(dict.fromkeys(source.official_domain for source in candidates)),
        field_targets=OFFICIAL_FIELD_TARGETS[: limits.max_fields_per_program],
        max_urls=len(candidates),
        stop_conditions=[
            "only fetch sources in this target's allowlisted domains",
            "only extract the listed field targets",
            "stop after one bounded pass over each scheduled URL",
            "send candidates to Verification for binding and human review; never publish here",
        ],
    )


def _known_domains(program: Program) -> set[str]:
    domains: set[str] = set()
    for value in (program.official_program_url, program.application_url, program.source.url):
        domain = official_institution_domain(str(value)) if value else None
        if domain:
            domains.add(domain)
    return domains


def _safe_official_url(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    if not is_allowed_official_url(text):
        return None
    return text


def _registry_scope_fields(source: SourcePolicy) -> tuple[str, list[str]]:
    category = source.category.value
    if category == "official_program_index":
        return "institution_index", _INDEX_FIELDS
    if category == "official_application_system":
        return "application_portal", _APPLICATION_FIELDS
    if category in {"official_program_page", "official_pdf_or_faq"}:
        return "programme_detail", _DETAIL_FIELDS
    return "programme_detail", _DETAIL_FIELDS


def _registry_priority(source: SourcePolicy) -> int:
    category = source.category.value
    return {
        "official_program_page": 1,
        "official_pdf_or_faq": 2,
        "official_application_system": 3,
        "official_program_index": 4,
    }.get(category, 99)


__all__ = [
    "OFFICIAL_FIELD_TARGETS",
    "SourceResearchLimits",
    "SourceResearchPlan",
    "SourceResearchSource",
    "SourceResearchTarget",
    "build_source_research_plan",
]
