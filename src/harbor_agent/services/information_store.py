"""Durable run and source-health ledger for the official information pipeline.

The catalog and the evidence candidates remain in the existing program store,
but fetch attempts must have their own append-only operational record.  This
module intentionally contains no crawling logic: it is the persistence port
used by every information agent and makes a refresh replayable and observable.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable
from uuid import uuid4

from harbor_agent.models import SourceHealthItem, SourceHealthSummary, SourcePolicy, SourceScope
from harbor_agent.services.program_store import DB_PATH, init_program_store


def init_information_store(db_path: Path | None = None) -> None:
    db_path = db_path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_program_store(db_path)
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS information_runs (
                run_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                selected_program_ids_json TEXT NOT NULL,
                planned_source_count INTEGER NOT NULL DEFAULT 0,
                attempted_source_count INTEGER NOT NULL DEFAULT 0,
                successful_source_count INTEGER NOT NULL DEFAULT 0,
                failed_source_count INTEGER NOT NULL DEFAULT 0,
                binding_warning_count INTEGER NOT NULL DEFAULT 0,
                warning_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS information_fetch_attempts (
                attempt_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                program_id TEXT,
                source_id TEXT NOT NULL,
                source_scope TEXT NOT NULL,
                requested_url TEXT NOT NULL,
                final_url TEXT,
                status TEXT NOT NULL,
                http_status INTEGER,
                checked_at TEXT NOT NULL,
                page_hash TEXT,
                snapshot_path TEXT,
                content_bytes INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                binding_status TEXT NOT NULL DEFAULT 'not_checked',
                binding_score INTEGER NOT NULL DEFAULT 0,
                extracted_field_count INTEGER NOT NULL DEFAULT 0,
                error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_information_attempt_source
                ON information_fetch_attempts(source_id, checked_at);
            CREATE INDEX IF NOT EXISTS idx_information_attempt_run
                ON information_fetch_attempts(run_id, checked_at);
            """
        )


def start_information_run(
    run_id: str,
    *,
    mode: str,
    selected_program_ids: Iterable[str],
    planned_source_count: int,
    db_path: Path | None = None,
) -> None:
    db_path = db_path or DB_PATH
    init_information_store(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO information_runs
            (run_id, mode, status, started_at, selected_program_ids_json, planned_source_count)
            VALUES (?, ?, 'RUNNING', ?, ?, ?)
            """,
            (
                run_id,
                mode,
                _now(),
                json.dumps(list(selected_program_ids), ensure_ascii=False),
                max(0, int(planned_source_count)),
            ),
        )


def record_fetch_attempt(
    run_id: str,
    *,
    program_id: str | None,
    source_id: str,
    source_scope: str | SourceScope,
    requested_url: str,
    snapshot: Any,
    binding_status: str = "not_checked",
    binding_score: int = 0,
    extracted_field_count: int = 0,
    db_path: Path | None = None,
) -> str:
    db_path = db_path or DB_PATH
    init_information_store(db_path)
    attempt_id = f"fetch_{uuid4().hex[:14]}"
    status = str(getattr(snapshot, "status", "UNKNOWN"))
    if hasattr(snapshot, "status") and hasattr(snapshot.status, "value"):
        status = snapshot.status.value
    scope = source_scope.value if isinstance(source_scope, SourceScope) else str(source_scope)
    checked_at = getattr(snapshot, "checked_at", None) or datetime.now(UTC)
    if isinstance(checked_at, datetime):
        checked_at = checked_at.isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO information_fetch_attempts
            (attempt_id, run_id, program_id, source_id, source_scope, requested_url, final_url,
             status, http_status, checked_at, page_hash, snapshot_path, content_bytes,
             duration_ms, attempts, binding_status, binding_score, extracted_field_count, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                run_id,
                program_id,
                source_id,
                scope,
                requested_url,
                getattr(snapshot, "final_url", None),
                status,
                getattr(snapshot, "http_status", None),
                checked_at,
                getattr(snapshot, "page_hash", None),
                getattr(snapshot, "snapshot_path", None),
                int(getattr(snapshot, "content_bytes", 0) or 0),
                int(getattr(snapshot, "duration_ms", 0) or 0),
                int(getattr(snapshot, "attempts", 0) or 0),
                binding_status,
                max(0, min(100, int(binding_score))),
                max(0, int(extracted_field_count)),
                getattr(snapshot, "error", None),
            ),
        )
    return attempt_id


def finish_information_run(
    run_id: str,
    *,
    status: str,
    attempted_source_count: int,
    successful_source_count: int,
    failed_source_count: int,
    binding_warning_count: int = 0,
    warnings: Iterable[str] = (),
    db_path: Path | None = None,
) -> None:
    db_path = db_path or DB_PATH
    init_information_store(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE information_runs
            SET status = ?, finished_at = ?, attempted_source_count = ?,
                successful_source_count = ?, failed_source_count = ?,
                binding_warning_count = ?, warning_json = ?
            WHERE run_id = ?
            """,
            (
                status,
                _now(),
                max(0, int(attempted_source_count)),
                max(0, int(successful_source_count)),
                max(0, int(failed_source_count)),
                max(0, int(binding_warning_count)),
                json.dumps(list(warnings)[:40], ensure_ascii=False),
                run_id,
            ),
        )


def update_information_run_plan(run_id: str, planned_source_count: int, *, db_path: Path | None = None) -> None:
    """Update a run when an index page discovers additional detail-page work."""

    db_path = db_path or DB_PATH
    init_information_store(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE information_runs SET planned_source_count = ? WHERE run_id = ?",
            (max(0, int(planned_source_count)), run_id),
        )


def latest_source_page_hash(source_id: str, *, db_path: Path | None = None) -> str | None:
    """Return the last stored content hash for change detection."""

    db_path = db_path or DB_PATH
    init_information_store(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT page_hash FROM information_fetch_attempts
            WHERE source_id = ? AND page_hash IS NOT NULL
            ORDER BY checked_at DESC, attempt_id DESC LIMIT 1
            """,
            (source_id,),
        ).fetchone()
    return str(row[0]) if row and row[0] else None


def source_health_summary(
    sources: Iterable[SourcePolicy],
    *,
    now: datetime | None = None,
    db_path: Path | None = None,
) -> SourceHealthSummary:
    """Return the latest operational health without exposing snapshot bodies."""

    db_path = db_path or DB_PATH
    init_information_store(db_path)
    current = now or datetime.now(UTC)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT a.*
            FROM information_fetch_attempts a
            JOIN (
                SELECT source_id, MAX(checked_at) AS max_checked_at
                FROM information_fetch_attempts GROUP BY source_id
            ) latest ON latest.source_id = a.source_id AND latest.max_checked_at = a.checked_at
            """
        ).fetchall()
        aggregate = conn.execute(
            """
            SELECT source_id, COUNT(*) AS attempts,
                   SUM(CASE WHEN status IN ('FETCH_OK', '200', 'OK') THEN 1 ELSE 0 END) AS successes,
                   AVG(duration_ms) AS avg_duration,
                   MAX(checked_at) AS last_checked_at,
                   MAX(CASE WHEN status IN ('FETCH_OK', '200', 'OK') THEN checked_at END) AS last_success_at,
                   MAX(CASE WHEN status NOT IN ('FETCH_OK', '200', 'OK') THEN checked_at END) AS last_failure_at
            FROM information_fetch_attempts GROUP BY source_id
            """
        ).fetchall()
        pending_by_source = {
            str(row["source_type"]): int(row["count"] or 0)
            for row in conn.execute(
                "SELECT source_type, COUNT(*) AS count FROM program_field_evidence WHERE review_required = 1 GROUP BY source_type"
            ).fetchall()
        }
        pending_by_program = {
            str(row["program_id"]): int(row["count"] or 0)
            for row in conn.execute(
                """
                SELECT program_id, COUNT(*) AS count
                FROM program_field_evidence
                WHERE review_required = 1
                GROUP BY program_id
                """
            ).fetchall()
        }
        pending_total = int(
            conn.execute(
                "SELECT COUNT(*) FROM program_field_evidence WHERE review_required = 1"
            ).fetchone()[0]
        )

    latest_by_source = {str(row["source_id"]): row for row in rows}
    aggregate_by_source = {str(row["source_id"]): row for row in aggregate}
    items: list[SourceHealthItem] = []
    registry_source_ids: set[str] = set()
    for source in sources:
        registry_source_ids.add(source.source_id)
        latest = latest_by_source.get(source.source_id)
        stats = aggregate_by_source.get(source.source_id)
        attempts = int(stats["attempts"] or 0) if stats else 0
        successes = int(stats["successes"] or 0) if stats else 0
        last_checked = _parse_dt(stats["last_checked_at"]) if stats else None
        last_success = _parse_dt(stats["last_success_at"]) if stats else None
        last_failure = _parse_dt(stats["last_failure_at"]) if stats else None
        state = _freshness_state(source.refresh_cadence, last_success, current)
        last_status = str(latest["status"]) if latest else "NEVER_RUN"
        if not _is_success_status(last_status) and last_status != "NEVER_RUN":
            state = "stale"
        if _is_success_status(last_status) and state == "fresh":
            next_action = "来源健康，按计划继续刷新"
        elif last_status == "NEVER_RUN":
            next_action = "安排首次抓取并保存页面快照"
        elif last_status != "FETCH_OK":
            next_action = "检查 robots、跳转和官网改版后重试"
        else:
            next_action = "重新抓取并由人工复核变化字段"
        items.append(
            SourceHealthItem(
                source_id=source.source_id,
                name=source.name,
                url=source.url,
                source_scope=_scope_for_source(source),
                last_status=last_status,
                last_checked_at=last_checked,
                last_success_at=last_success,
                last_failure_at=last_failure,
                last_http_status=int(latest["http_status"]) if latest and latest["http_status"] is not None else None,
                last_page_hash=str(latest["page_hash"]) if latest and latest["page_hash"] else None,
                attempt_count=attempts,
                success_count=successes,
                failure_count=max(0, attempts - successes),
                failure_rate=round((attempts - successes) / attempts, 3) if attempts else 0,
                average_duration_ms=round(float(stats["avg_duration"] or 0)) if stats else 0,
                review_pending_count=pending_by_source.get(
                    source.category.value if hasattr(source.category, "value") else str(source.category),
                    0,
                ),
                freshness_state=state,
                next_action=next_action,
            )
        )
    # Programme detail URLs are discovered dynamically and are not part of the
    # static source registry. They are the most important truth-bearing sources,
    # so expose every observed one in the same health view.
    for source_id, stats in aggregate_by_source.items():
        if source_id in registry_source_ids:
            continue
        latest = latest_by_source.get(source_id)
        if latest is None:
            continue
        attempts = int(stats["attempts"] or 0)
        successes = int(stats["successes"] or 0)
        last_checked = _parse_dt(stats["last_checked_at"])
        last_success = _parse_dt(stats["last_success_at"])
        last_failure = _parse_dt(stats["last_failure_at"])
        last_status = str(latest["status"])
        state = _freshness_state("daily", last_success, current)
        if not _is_success_status(last_status):
            state = "stale"
        program_id = str(latest["program_id"] or "")
        requested_url = str(latest["requested_url"] or latest["final_url"] or "")
        scope_value = str(latest["source_scope"] or SourceScope.programme_detail.value)
        try:
            scope = SourceScope(scope_value)
        except ValueError:
            scope = SourceScope.programme_detail
        items.append(
            SourceHealthItem(
                source_id=source_id,
                name=(f"{program_id} · 项目详情页" if program_id else f"{source_id} · 动态来源"),
                url=requested_url,
                source_scope=scope,
                last_status=last_status,
                last_checked_at=last_checked,
                last_success_at=last_success,
                last_failure_at=last_failure,
                last_http_status=int(latest["http_status"]) if latest["http_status"] is not None else None,
                last_page_hash=str(latest["page_hash"]) if latest["page_hash"] else None,
                attempt_count=attempts,
                success_count=successes,
                failure_count=max(0, attempts - successes),
                failure_rate=round((attempts - successes) / attempts, 3) if attempts else 0,
                average_duration_ms=round(float(stats["avg_duration"] or 0)),
                review_pending_count=pending_by_program.get(program_id, 0),
                freshness_state=state,
                next_action=(
                    "项目详情页健康，可继续进入字段审核。"
                    if _is_success_status(last_status) and state == "fresh"
                    else "重新抓取项目详情页，并检查项目身份绑定与官网改版。"
                ),
            )
        )
    items.sort(key=lambda item: (item.freshness_state == "fresh", item.last_status == "FETCH_OK", item.source_id))
    return SourceHealthSummary(
        generated_at=current,
        total_sources=len(items),
        healthy_sources=sum(
            item.freshness_state == "fresh" and _is_success_status(item.last_status)
            for item in items
        ),
        due_sources=sum(item.freshness_state == "due" for item in items),
        stale_sources=sum(item.freshness_state == "stale" for item in items),
        never_run_sources=sum(item.last_status == "NEVER_RUN" for item in items),
        failing_sources=sum(
            item.last_status != "NEVER_RUN" and not _is_success_status(item.last_status)
            for item in items
        ),
        # A category may be represented by multiple source-registry entries, so
        # summing item counts would overstate the global queue.
        pending_review_count=pending_total,
        items=items,
    )


def _is_success_status(value: str) -> bool:
    return value in {"FETCH_OK", "200", "OK"}


def _scope_for_source(source: SourcePolicy) -> SourceScope:
    category = source.category.value if hasattr(source.category, "value") else str(source.category)
    if "index" in category:
        return SourceScope.institution_index
    if "application" in category:
        return SourceScope.application_portal
    if "community" in category:
        return SourceScope.community_reference
    if "methodology" in category or "writing" in category:
        return SourceScope.methodology
    return SourceScope.programme_detail


def _freshness_state(cadence: str, last_success: datetime | None, now: datetime) -> str:
    if last_success is None:
        return "unknown"
    seconds = _cadence_seconds(cadence)
    age = max(0, (now - last_success).total_seconds())
    if age <= seconds:
        return "fresh"
    if age <= seconds * 2:
        return "due"
    return "stale"


def _cadence_seconds(value: str) -> float:
    text = (value or "").lower()
    if "manual" in text or "on_demand" in text:
        return 31536000
    if "quarter" in text:
        return 7776000
    match = re.search(r"(\d+)\s*(hour|day|week|month)", text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        return float(amount * {"hour": 3600, "day": 86400, "week": 604800, "month": 2592000}[unit])
    if "hour" in text:
        return 3600
    if "week" in text:
        return 604800
    if "month" in text or "cycle" in text:
        return 2592000
    return 86400


def _connect(db_path):
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _now() -> str:
    return datetime.now(UTC).isoformat()
