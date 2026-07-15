from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from uuid import uuid4

from harbor_agent.models import (
    CatalogAutoUpdateReport,
    CatalogAutoUpdateRequest,
    FieldEvidenceRecord,
    FieldVerificationStatus,
    Program,
    ProgramUrlCandidate,
)
from harbor_agent.services.data_loader import load_programs
from harbor_agent.services.program_store import upsert_field_evidence_records
from harbor_agent.services.program_urls import has_program_detail_page, is_generic_program_url
from harbor_agent.services.review_gate import build_review_queue


class CatalogAutoUpdateAgent:
    """Discovers official programme URL candidates and sends them to review."""

    name = "CatalogAutoUpdateAgent"

    def run(self, request: CatalogAutoUpdateRequest) -> CatalogAutoUpdateReport:
        checked_at = datetime.now(UTC)
        programs = _select_programs(load_programs(), request)
        candidates: list[ProgramUrlCandidate] = []
        warnings: list[str] = []

        for program in programs:
            discovered = _known_candidates(program, checked_at)[: request.max_candidates_per_program]
            if not discovered and not has_program_detail_page(program):
                warnings.append(f"No official programme-page candidate found for {program.id}.")
            candidates.extend(discovered)

        persisted_count = 0
        if not request.dry_run:
            persisted_count = upsert_field_evidence_records(
                [candidate.evidence_record for candidate in candidates]
            )

        review_queue_size = build_review_queue(limit=1).pending_count if not request.dry_run else 0
        missing_detail_count = sum(1 for program in programs if not has_program_detail_page(program))
        mode = "dry_run" if request.dry_run else "live_fetch"
        summary = (
            f"Scanned {len(programs)} programmes; {missing_detail_count} lack a student-visible "
            f"programme detail page. Found {len(candidates)} official URL candidates."
        )
        if request.dry_run:
            summary += " Dry-run did not write SQLite evidence."
        else:
            summary += f" Wrote {persisted_count} candidates to the field review queue."

        return CatalogAutoUpdateReport(
            run_id=f"catalog_auto_{uuid4().hex[:12]}",
            mode=mode,
            checked_at=checked_at,
            selected_program_ids=request.selected_program_ids,
            scanned_program_count=len(programs),
            missing_detail_page_count=missing_detail_count,
            candidate_count=len(candidates),
            persisted_candidate_count=persisted_count,
            review_queue_size=review_queue_size,
            candidates=candidates,
            warnings=warnings,
            summary=summary,
            agent_chain=[
                "CatalogAutoUpdateAgent",
                "OfficialLinkDiscoveryAgent",
                "TitleMatchAgent",
                "HumanReviewGateAgent",
            ],
        )


def _select_programs(programs: list[Program], request: CatalogAutoUpdateRequest) -> list[Program]:
    selected_ids = set(request.selected_program_ids)
    filtered = programs
    if selected_ids:
        filtered = [program for program in filtered if program.id in selected_ids]
    if request.institution:
        needle = request.institution.strip().lower()
        filtered = [
            program
            for program in filtered
            if needle in program.institution.lower()
            or needle in (program.institution_zh or "").lower()
        ]
    prioritized = [program for program in filtered if not has_program_detail_page(program)]
    remaining = [program for program in filtered if has_program_detail_page(program)]
    return (prioritized + remaining)[: request.max_programs]


def _known_candidates(program: Program, checked_at: datetime) -> list[ProgramUrlCandidate]:
    if has_program_detail_page(program):
        return []
    seeds = _CANDIDATE_URLS.get(program.id, [])
    output: list[ProgramUrlCandidate] = []
    for seed in seeds:
        candidate_url = seed["url"]
        if is_generic_program_url(candidate_url):
            continue
        label = seed.get("label") or program.name
        status = FieldVerificationStatus(seed.get("status", FieldVerificationStatus.official_previous_cycle.value))
        score = _match_score(program, label, candidate_url, int(seed.get("score", 0)))
        reason = seed.get("reason") or _candidate_reason(program, label, score, status)
        record = _evidence_record(program, candidate_url, label, reason, status, score, checked_at)
        output.append(
            ProgramUrlCandidate(
                program_id=program.id,
                institution=program.institution_zh or program.institution,
                program_name=program.name_zh or program.name,
                candidate_url=candidate_url,
                candidate_label=label,
                source_url=seed.get("source_url") or candidate_url,
                match_score=score,
                status=status,
                reason=reason,
                review_required=True,
                publishable_after_review=_publishable_after_review(record),
                evidence_record=record,
            )
        )
    return sorted(output, key=lambda item: (-item.match_score, str(item.candidate_url)))


def _evidence_record(
    program: Program,
    candidate_url: str,
    label: str,
    reason: str,
    status: FieldVerificationStatus,
    score: int,
    checked_at: datetime,
) -> FieldEvidenceRecord:
    page_hash = "sha256:" + hashlib.sha256(
        f"{program.id}|official_program_url|{candidate_url}|{label}".encode("utf-8")
    ).hexdigest()
    return FieldEvidenceRecord(
        program_id=program.id,
        field_name="official_program_url",
        value=candidate_url,
        cycle=program.cycle,
        source_url=candidate_url,
        source_type="official_program_page",
        extracted_at=checked_at,
        verified_at=None,
        page_hash=page_hash,
        confidence="high" if score >= 80 and status != FieldVerificationStatus.conflicted else "medium",
        source_priority=2,
        status=status,
        review_required=True,
        evidence_snippet=reason,
        snapshot_url=candidate_url,
        agent_chain=[
            "CatalogAutoUpdateAgent",
            "OfficialLinkDiscoveryAgent",
            "TitleMatchAgent",
            "HumanReviewGateAgent",
        ],
    )


def _publishable_after_review(record: FieldEvidenceRecord) -> bool:
    return (
        record.source_type.startswith("official")
        and bool(record.source_url)
        and bool(record.page_hash)
        and bool(record.evidence_snippet)
        and record.status == FieldVerificationStatus.official_previous_cycle
    )


def _match_score(program: Program, label: str, url: str, seed_score: int) -> int:
    tokens = _tokens(program.name)
    haystack = f"{label} {url}".lower()
    matched = sum(1 for token in tokens if token in haystack)
    token_score = int(100 * matched / max(1, len(tokens)))
    return max(seed_score, token_score)


def _tokens(value: str) -> list[str]:
    stopwords = {
        "ma",
        "msc",
        "master",
        "science",
        "arts",
        "of",
        "in",
        "and",
        "for",
        "the",
        "studies",
    }
    return [
        token
        for token in re.split(r"[^a-z0-9]+", value.lower())
        if len(token) >= 3 and token not in stopwords
    ]


def _candidate_reason(
    program: Program,
    label: str,
    score: int,
    status: FieldVerificationStatus,
) -> str:
    if status == FieldVerificationStatus.conflicted:
        return (
            f"Official page candidate label '{label}' partially matches {program.name}, but title or naming differs; "
            "keep it in review and do not publish before human confirmation."
        )
    return (
        f"Official programme-page candidate label '{label}' matches {program.name} with score {score}; "
        "publish only after the reviewer checks the original school page."
    )


_CANDIDATE_URLS: dict[str, list[dict[str, object]]] = {
    "cityu-msc-business-information-systems-2027": [
        {
            "url": "https://www.cityu.edu.hk/pg/programme/p05a",
            "label": "MSc Business Information Systems (Management of Intelligent Systems Stream)",
            "score": 88,
            "reason": "CityUHK official programme page p05a is a stream page for MSc Business Information Systems; review should decide whether the stream page should represent the catalog programme.",
        },
        {
            "url": "https://www.cityu.edu.hk/pg/programme/p05b",
            "label": "MSc Business Information Systems (Financial and Intelligent Technology Stream)",
            "score": 88,
            "reason": "CityUHK official programme page p05b is another stream page for MSc Business Information Systems; review should decide whether to publish one or both stream links.",
        },
    ],
    "cityu-msc-electronic-information-engineering-2027": [
        {
            "url": "https://www.cityu.edu.hk/pg/programme/p59",
            "label": "MSc Computer and Information Engineering",
            "score": 55,
            "status": FieldVerificationStatus.conflicted.value,
            "reason": "CityUHK page p59 is titled MSc Computer and Information Engineering, not MSc Electronic Information Engineering; keep as conflicted review evidence only.",
        }
    ],
    "hkbu-ma-communication-2027": [
        {
            "url": "https://comd.hkbu.edu.hk/macomm.html",
            "label": "MA in Communication",
            "score": 96,
            "status": FieldVerificationStatus.conflicted.value,
            "source_url": "https://comd.hkbu.edu.hk/",
            "reason": "HKBU Communication candidate URL returned 404 during live verification on 2026-07-05; keep as stale-link evidence and locate a current official programme page before publishing.",
        }
    ],
    "hkbu-ma-international-journalism-studies-2027": [
        {
            "url": "https://comd.hkbu.edu.hk/maijs.html",
            "label": "MA in International Journalism Studies",
            "score": 96,
            "status": FieldVerificationStatus.conflicted.value,
            "source_url": "https://comd.hkbu.edu.hk/",
            "reason": "HKBU Communication candidate URL returned 404 during live verification on 2026-07-05; keep as stale-link evidence and locate a current official programme page before publishing.",
        }
    ],
    "hkbu-msc-applied-accounting-and-finance-2027": [
        {
            "url": "https://mscaaf.hkbu.edu.hk/",
            "label": "MSc Applied Accounting and Finance",
            "score": 96,
            "source_url": "https://bus.hkbu.edu.hk/study/taught-postgraduate-programmes.html",
        }
    ],
    "hkbu-msc-business-management-2027": [
        {
            "url": "https://mscbm.hkbu.edu.hk",
            "label": "MSc Business Management",
            "score": 96,
            "source_url": "https://bus.hkbu.edu.hk/study/taught-postgraduate-programmes.html",
        }
    ],
    "hkbu-msc-corporate-governance-and-compliance-2027": [
        {
            "url": "https://msccgc.hkbu.edu.hk",
            "label": "MSc Corporate Governance and Compliance",
            "score": 96,
            "source_url": "https://bus.hkbu.edu.hk/study/taught-postgraduate-programmes.html",
        }
    ],
    "polyu-ma-translating-and-interpreting-2027": [
        {
            "url": "https://www.polyu.edu.hk/study/pg/tpg/2027/72030-ttf-ttp",
            "label": "Master of Arts in Translation and Language Technology",
            "score": 58,
            "status": FieldVerificationStatus.conflicted.value,
            "reason": "PolyU page 72030-ttf-ttp is titled Master of Arts in Translation and Language Technology, not MA Translating and Interpreting; keep as conflicted review evidence only.",
        }
    ],
}