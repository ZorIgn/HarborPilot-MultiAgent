from __future__ import annotations

import json
from functools import lru_cache
from datetime import date
from typing import Any

from harbor_agent.models import Program
from harbor_agent.services.data_loader import DATA_DIR


QS_MASTER_IMPORT = DATA_DIR / "external_candidates" / "qs_master_applications_candidates.json"


@lru_cache(maxsize=1)
def load_qs_master_applications_import() -> dict[str, Any]:
    """Load the curated GradWindow import used as source-discovery evidence."""
    if not QS_MASTER_IMPORT.exists():
        return {
            "source_id": "qs_master_applications_github",
            "source_name": "GradWindow / QS Master Applications",
            "source_url": "https://github.com/lione12138/qs-master-applications",
            "status": "missing",
            "candidate_count": 0,
            "candidates": [],
        }
    with QS_MASTER_IMPORT.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    data.setdefault("candidates", [])
    data.setdefault("candidate_count", len(data["candidates"]))
    return data


def qs_candidates_for_programs(programs: list[Program]) -> list[dict[str, Any]]:
    data = load_qs_master_applications_import()
    candidates = data.get("candidates", [])
    if not isinstance(candidates, list):
        return []

    program_ids = {program.id for program in programs}
    institution_names = {
        _normalize(program.institution)
        for program in programs
    } | {
        _normalize(program.institution_zh or "")
        for program in programs
    }
    matched: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        harbor_ids = set(candidate.get("harbor_program_ids") or [])
        institution = _normalize(str(candidate.get("institution") or ""))
        institution_zh = _normalize(str(candidate.get("institution_zh") or ""))
        if harbor_ids & program_ids or institution in institution_names or institution_zh in institution_names:
            matched.append(candidate)
    return matched


def qs_import_summary_for_programs(programs: list[Program]) -> dict[str, Any]:
    data = load_qs_master_applications_import()
    candidates = qs_candidates_for_programs(programs)
    return {
        "source_id": data.get("source_id", "qs_master_applications_github"),
        "source_name": data.get("source_name", "GradWindow / QS Master Applications"),
        "source_url": data.get("source_url", "https://github.com/lione12138/qs-master-applications"),
        "status": data.get("status", "missing"),
        "imported_at": data.get("imported_at"),
        "license_note": data.get("license_note"),
        "coverage_note": data.get("coverage_note"),
        "methodology": data.get("methodology", []),
        "matched_candidate_count": len(candidates),
        "matched_candidates": candidates,
        "use_boundary": [
            "可用于发现项目、补全官网入口、理解上一申请季窗口和申请系统位置。",
            "不能自动写入正式截止日期、学费、语言要求、材料要求。",
            "给学生展示时应写成“官网线索/上一申请季参考”，不能写成“学校已确认”。",
        ],
    }


def qs_candidate_for_program(program: Program) -> dict[str, Any] | None:
    candidates = qs_candidates_for_programs([program])
    direct = [
        candidate
        for candidate in candidates
        if program.id in set(candidate.get("harbor_program_ids") or [])
    ]
    return (direct or candidates or [None])[0]


def qs_evidence_note_for_program(program: Program) -> str | None:
    candidate = qs_candidate_for_program(program)
    if not candidate:
        return None
    window_status = str(candidate.get("window_status") or "")
    source_name = "GradWindow/QS Master Applications"
    if window_status.startswith("official_previous_cycle"):
        closes_at = candidate.get("closes_at")
        opens_at = candidate.get("opens_at")
        if opens_at and closes_at:
            return (
                f"{source_name} 已导入上一申请季官网窗口：{opens_at} 至 {closes_at}。"
                "当前申请季仍需回学校官网确认后才能作为正式截止。"
            )
        return f"{source_name} 已导入上一申请季官网线索；当前申请季仍需回学校官网确认。"
    if candidate.get("application_url") or candidate.get("source_url"):
        return f"{source_name} 已定位官网项目页/申请入口；截止日期、学费、语言和材料仍需逐项确认。"
    return f"{source_name} 已提供项目发现线索；正式要求仍以学校官网原文为准。"


def qs_previous_cycle_deadline(program: Program) -> date | None:
    candidate = qs_candidate_for_program(program)
    if not candidate:
        return None
    closes_at = candidate.get("closes_at")
    if not isinstance(closes_at, str):
        return None
    try:
        return date.fromisoformat(closes_at)
    except ValueError:
        return None


def qs_previous_cycle_open_date(program: Program) -> date | None:
    candidate = qs_candidate_for_program(program)
    if not candidate:
        return None
    opens_at = candidate.get("opens_at")
    if not isinstance(opens_at, str):
        return None
    try:
        return date.fromisoformat(opens_at)
    except ValueError:
        return None


def qs_source_url_for_program(program: Program) -> str | None:
    candidate = qs_candidate_for_program(program)
    if not candidate:
        return None
    return candidate.get("source_url") or candidate.get("application_url") or candidate.get("admissions_url")


def qs_window_status_for_program(program: Program) -> str | None:
    candidate = qs_candidate_for_program(program)
    if not candidate:
        return None
    return str(candidate.get("window_status") or "")


def _normalize(value: str) -> str:
    return " ".join(value.lower().strip().split())
