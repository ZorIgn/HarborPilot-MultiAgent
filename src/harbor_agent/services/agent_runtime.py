from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from harbor_agent.models import AgentStatus
from harbor_agent.runtime.sanitizer import sanitize_runtime_payload
from harbor_agent.services.data_loader import DATA_DIR


DB_PATH = DATA_DIR / "agent_runtime.sqlite"

# Checkpoint retention is intentionally conservative.  A workflow may create
# several snapshots during its current UTC day, but historical days keep only a
# couple of recovery points.  The global cap is a safety net for many workflows
# and prevents the append-only checkpoint table from growing without bound.
CHECKPOINT_MAX_PER_WORKFLOW = 8
CHECKPOINT_DAILY_KEEP = 2
CHECKPOINT_MAX_TOTAL = 200


def start_agent_run(workflow_id: str, workflow_name: str | None = None) -> None:
    _ensure_schema()
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO agent_runs
            (workflow_id, workflow_name, status, current_step, created_at, updated_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (workflow_id, workflow_name or "unknown", "RUNNING", "", now, now, "{}"),
        )
    log_agent_event("run", workflow_id, "RUN_STARTED", workflow_name or "unknown")


def complete_agent_run(workflow_id: str, status: str = "COMPLETED") -> None:
    _ensure_schema()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE agent_runs
            SET status = ?, updated_at = ?
            WHERE workflow_id = ?
            """,
            (status, _now(), workflow_id),
        )
    log_agent_event("run", workflow_id, "RUN_" + status, "workflow finished with status " + status)


def record_agent_step(
    *,
    workflow_id: str,
    node: str,
    status: AgentStatus,
    input_summary: str,
    output_summary: str,
    tool_calls: list[str],
    model: str,
    started_at: datetime,
    finished_at: datetime,
    needs_human_reason: str | None = None,
    max_attempts: int = 2,
) -> None:
    _ensure_schema()
    attempt = _next_attempt(workflow_id, node)
    step_id = f"{workflow_id}:{node}:{attempt}"
    run_status = _run_status_for(status)
    assigned_to = "human_reviewer" if status == AgentStatus.needs_human else node
    can_retry = status == AgentStatus.failed and attempt < max_attempts
    payload = {
        "tool_calls": tool_calls,
        "model": model,
        "can_retry": can_retry,
        "handoff_to": assigned_to,
        "needs_human_reason": needs_human_reason,
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO agent_steps
            (step_id, workflow_id, node, status, attempt, max_attempts, assigned_to,
             started_at, finished_at, input_summary, output_summary, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                step_id,
                workflow_id,
                node,
                status.value,
                attempt,
                max_attempts,
                assigned_to,
                started_at.isoformat(),
                finished_at.isoformat(),
                input_summary,
                output_summary,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.execute(
            """
            UPDATE agent_runs
            SET status = ?, current_step = ?, updated_at = ?
            WHERE workflow_id = ?
            """,
            (run_status, node, _now(), workflow_id),
        )
    log_agent_event(
        "run",
        workflow_id,
        "STEP_" + status.value,
        output_summary,
        {"step_id": step_id, "node": node, "attempt": attempt, "assigned_to": assigned_to, "can_retry": can_retry},
    )


def enqueue_agent_job(
    workflow_name: str,
    payload_summary: str,
    payload: dict[str, Any] | None = None,
    *,
    priority: int = 50,
    max_attempts: int = 2,
) -> dict[str, Any]:
    _ensure_schema()
    job_id = f"job_{uuid4().hex[:12]}"
    now = _now()
    priority = max(0, min(100, int(priority)))
    max_attempts = max(1, min(10, int(max_attempts)))
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_jobs
            (job_id, workflow_name, status, priority, attempts, max_attempts, payload_summary, payload_json, assigned_to, last_error, created_at, updated_at)
            VALUES (?, ?, 'QUEUED', ?, 0, ?, ?, ?, NULL, NULL, ?, ?)
            """,
            (job_id, workflow_name, priority, max_attempts, payload_summary, json.dumps(payload or {}, ensure_ascii=False), now, now),
        )
    log_agent_event("job", job_id, "JOB_QUEUED", payload_summary, {"workflow_name": workflow_name, "priority": priority, "max_attempts": max_attempts})
    return {"job_id": job_id, "workflow_name": workflow_name, "status": "QUEUED", "priority": priority, "attempts": 0, "max_attempts": max_attempts}


def enqueue_catalog_refresh_plan(
    *,
    selected_program_ids: list[str] | None = None,
    institution: str | None = None,
    dry_run: bool = False,
    include_community: bool = True,
    max_programs: int = 48,
    max_candidates_per_program: int = 6,
    max_sources_per_program: int = 8,
    include_data_acquisition: bool = True,
    include_crawl_queue: bool = True,
) -> list[dict[str, Any]]:
    selected_ids = list(selected_program_ids or [])
    jobs: list[dict[str, Any]] = []
    jobs.append(
        enqueue_agent_job(
            "catalog_auto_update",
            "Refresh official programme detail URL candidates",
            {
                "selected_program_ids": selected_ids,
                "institution": institution,
                "dry_run": dry_run,
                "max_programs": max_programs,
                "max_candidates_per_program": max_candidates_per_program,
            },
            priority=90,
            max_attempts=2,
        )
    )
    if include_data_acquisition:
        jobs.append(
            enqueue_agent_job(
                "data_acquisition",
                "Collect official field evidence for programmes",
                {
                    "selected_program_ids": selected_ids,
                    "include_community": include_community,
                    "dry_run": dry_run,
                    "max_sources_per_program": max_sources_per_program,
                },
                priority=80,
                max_attempts=2,
            )
        )
    if include_crawl_queue:
        jobs.append(
            enqueue_agent_job(
                "crawl_queue",
                "Build official crawl queue for source review",
                {
                    "selected_program_ids": selected_ids,
                    "include_community": include_community,
                    "max_sources_per_program": max_sources_per_program,
                },
                priority=70,
                max_attempts=2,
            )
        )
    log_agent_event(
        "job",
        "catalog_refresh_plan",
        "CATALOG_REFRESH_PLAN_QUEUED",
        f"queued {len(jobs)} catalog refresh jobs",
        {
            "selected_program_count": len(selected_ids),
            "institution": institution,
            "dry_run": dry_run,
            "include_community": include_community,
            "job_ids": [job["job_id"] for job in jobs],
        },
    )
    return jobs

def claim_next_agent_job(assigned_to: str = "local_agent_worker") -> dict[str, Any] | None:
    _ensure_schema()
    now = _now()
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE agent_jobs
            SET status = 'RUNNING', attempts = attempts + 1, assigned_to = ?, updated_at = ?
            WHERE job_id = (
                SELECT job_id
                FROM agent_jobs
                WHERE status = 'QUEUED' AND attempts < max_attempts
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
            )
            AND status = 'QUEUED'
            RETURNING job_id, workflow_name, status, priority, attempts, max_attempts, payload_summary, payload_json, assigned_to, last_error, created_at, updated_at
            """,
            (assigned_to, now),
        ).fetchone()
        if row is None:
            return None
    output = dict(row)
    output["payload"] = json.loads(output.pop("payload_json") or "{}")
    log_agent_event("job", output["job_id"], "JOB_CLAIMED", "worker claimed job", {"assigned_to": assigned_to, "attempt": output["attempts"]})
    return output


def complete_agent_job(job_id: str, status: str = "COMPLETED", summary: str = "") -> None:
    _ensure_schema()
    normalized = status.upper()
    with _connect() as conn:
        row = conn.execute("SELECT payload_json, attempts, max_attempts FROM agent_jobs WHERE job_id = ?", (job_id,)).fetchone()
        payload_json = row["payload_json"] if row else "{}"
        payload_patch = {"worker_summary": summary, "can_retry": normalized == "FAILED" and row is not None and int(row["attempts"] or 0) < int(row["max_attempts"] or 1)}
        conn.execute(
            """
            UPDATE agent_jobs
            SET status = ?, payload_json = ?, last_error = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (normalized, _merge_payload(payload_json, payload_patch), summary if normalized == "FAILED" else None, _now(), job_id),
        )
    log_agent_event("job", job_id, "JOB_" + normalized, summary, payload_patch)


def retry_agent_job(job_id: str, reviewer_id: str = "local_admin") -> dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT job_id, status, attempts, max_attempts FROM agent_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            return {"ok": False, "message": "job not found"}
        if int(row["attempts"] or 0) >= int(row["max_attempts"] or 1):
            return {"ok": False, "message": "job has reached max attempts"}
        if row["status"] not in {"FAILED", "NEEDS_HUMAN", "RETRY_READY"}:
            return {"ok": False, "message": "job is not retryable from status " + str(row["status"])}
        conn.execute(
            """
            UPDATE agent_jobs
            SET status = 'QUEUED', assigned_to = NULL, last_error = NULL, updated_at = ?
            WHERE job_id = ?
            """,
            (_now(), job_id),
        )
    log_agent_event("job", job_id, "JOB_REQUEUED", "retry requested", {"reviewer_id": reviewer_id})
    return {"ok": True, "job_id": job_id, "status": "QUEUED"}


def list_agent_jobs(limit: int = 80) -> list[dict[str, Any]]:
    _ensure_schema()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT job_id, workflow_name, status, priority, attempts, max_attempts, payload_summary, payload_json, assigned_to, last_error, created_at, updated_at
            FROM agent_jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_job_dict(row) for row in rows]


def list_agent_runs(limit: int = 80) -> list[dict[str, Any]]:
    _ensure_schema()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT workflow_id, workflow_name, status, current_step, created_at, updated_at
            FROM agent_runs
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_agent_run(workflow_id: str) -> dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        run = conn.execute(
            """
            SELECT workflow_id, workflow_name, status, current_step, created_at, updated_at
            FROM agent_runs
            WHERE workflow_id = ?
            """,
            (workflow_id,),
        ).fetchone()
        steps = conn.execute(
            """
            SELECT step_id, node, status, attempt, max_attempts, assigned_to,
                   started_at, finished_at, input_summary, output_summary, payload_json
            FROM agent_steps
            WHERE workflow_id = ?
            ORDER BY started_at ASC, attempt ASC
            """,
            (workflow_id,),
        ).fetchall()
    return {
        "run": dict(run) if run else None,
        "steps": [_step_dict(row) for row in steps],
        "events": list_agent_events(entity_type="run", entity_id=workflow_id, limit=120),
    }


def request_step_retry(workflow_id: str, step_id: str, reviewer_id: str = "local_admin") -> dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM agent_steps WHERE workflow_id = ? AND step_id = ?",
            (workflow_id, step_id),
        ).fetchone()
        if row is None:
            return {"ok": False, "message": "step not found"}
        retry_job = enqueue_agent_job(
            workflow_name=f"retry:{row['node']}",
            payload_summary=f"Retry {row['node']} for {workflow_id}",
            payload={"workflow_id": workflow_id, "step_id": step_id, "node": row["node"], "reviewer_id": reviewer_id},
            priority=80,
        )
        conn.execute(
            "UPDATE agent_steps SET status = ?, assigned_to = ?, payload_json = ? WHERE step_id = ?",
            (
                "RETRY_REQUESTED",
                reviewer_id,
                _merge_payload(row["payload_json"], {"retry_job_id": retry_job["job_id"], "retry_requested_by": reviewer_id, "retry_requested_at": _now()}),
                step_id,
            ),
        )
        conn.execute(
            "UPDATE agent_runs SET status = ?, current_step = ?, updated_at = ? WHERE workflow_id = ?",
            ("RETRY_REQUESTED", row["node"], _now(), workflow_id),
        )
    log_agent_event("run", workflow_id, "STEP_RETRY_REQUESTED", "retry requested", {"step_id": step_id, "reviewer_id": reviewer_id, "job_id": retry_job["job_id"]})
    return {"ok": True, "job": retry_job, "status": "RETRY_REQUESTED"}


def handoff_step(workflow_id: str, step_id: str, assignee: str, reason: str) -> dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM agent_steps WHERE workflow_id = ? AND step_id = ?",
            (workflow_id, step_id),
        ).fetchone()
        if row is None:
            return {"ok": False, "message": "step not found"}
        conn.execute(
            "UPDATE agent_steps SET status = ?, assigned_to = ?, payload_json = ? WHERE step_id = ?",
            (
                AgentStatus.needs_human.value,
                assignee,
                _merge_payload(row["payload_json"], {"handoff_reason": reason, "handoff_at": _now()}),
                step_id,
            ),
        )
        conn.execute(
            "UPDATE agent_runs SET status = ?, current_step = ?, updated_at = ? WHERE workflow_id = ?",
            ("NEEDS_HUMAN", row["node"], _now(), workflow_id),
        )
    log_agent_event("run", workflow_id, "STEP_HANDOFF", reason, {"step_id": step_id, "assignee": assignee})
    return {"ok": True, "assigned_to": assignee, "reason": reason}


def resolve_handoff_step(
    workflow_id: str,
    step_id: str,
    reviewer_id: str,
    decision: str,
    note: str = "",
) -> dict[str, Any]:
    _ensure_schema()
    if decision not in {"resume", "fail", "complete"}:
        return {"ok": False, "message": "decision must be resume, fail, or complete"}
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM agent_steps WHERE workflow_id = ? AND step_id = ?",
            (workflow_id, step_id),
        ).fetchone()
        if row is None:
            return {"ok": False, "message": "step not found"}
        next_step_status = "COMPLETED" if decision in {"resume", "complete"} else "FAILED"
        next_run_status = "RUNNING" if decision == "resume" else next_step_status
        conn.execute(
            "UPDATE agent_steps SET status = ?, assigned_to = ?, payload_json = ? WHERE step_id = ?",
            (
                next_step_status,
                reviewer_id,
                _merge_payload(
                    row["payload_json"],
                    {
                        "handoff_resolved_by": reviewer_id,
                        "handoff_decision": decision,
                        "handoff_note": note,
                        "handoff_resolved_at": _now(),
                    },
                ),
                step_id,
            ),
        )
        conn.execute(
            "UPDATE agent_runs SET status = ?, current_step = ?, updated_at = ? WHERE workflow_id = ?",
            (next_run_status, row["node"], _now(), workflow_id),
        )
    log_agent_event("run", workflow_id, "STEP_HANDOFF_RESOLVED", note or decision, {"step_id": step_id, "reviewer_id": reviewer_id, "decision": decision})
    return {"ok": True, "status": next_run_status, "step_status": next_step_status}


def rollback_agent_run(
    workflow_id: str,
    target_step_id: str,
    reviewer_id: str = "local_admin",
    reason: str = "Rollback requested by operator.",
    enqueue_retry: bool = True,
) -> dict[str, Any]:
    _ensure_schema()
    retry_job: dict[str, Any] | None = None
    with _connect() as conn:
        target = conn.execute(
            "SELECT * FROM agent_steps WHERE workflow_id = ? AND step_id = ?",
            (workflow_id, target_step_id),
        ).fetchone()
        if target is None:
            return {"ok": False, "message": "target step not found"}
        later_steps = conn.execute(
            """
            SELECT step_id, payload_json
            FROM agent_steps
            WHERE workflow_id = ?
              AND (started_at > ? OR (started_at = ? AND attempt > ?))
            """,
            (workflow_id, target["started_at"], target["started_at"], target["attempt"]),
        ).fetchall()
        for row in later_steps:
            conn.execute(
                "UPDATE agent_steps SET status = ?, assigned_to = ?, payload_json = ? WHERE step_id = ?",
                (
                    "ROLLED_BACK",
                    reviewer_id,
                    _merge_payload(
                        row["payload_json"],
                        {
                            "rolled_back_by": reviewer_id,
                            "rolled_back_at": _now(),
                            "rollback_target_step_id": target_step_id,
                            "rollback_reason": reason,
                        },
                    ),
                    row["step_id"],
                ),
            )
        conn.execute(
            "UPDATE agent_steps SET status = ?, assigned_to = ?, payload_json = ? WHERE step_id = ?",
            (
                "ROLLBACK_TARGET",
                reviewer_id,
                _merge_payload(
                    target["payload_json"],
                    {
                        "rollback_selected_by": reviewer_id,
                        "rollback_selected_at": _now(),
                        "rollback_reason": reason,
                    },
                ),
                target_step_id,
            ),
        )
        conn.execute(
            "UPDATE agent_runs SET status = ?, current_step = ?, updated_at = ? WHERE workflow_id = ?",
            ("ROLLED_BACK", target["node"], _now(), workflow_id),
        )
    if enqueue_retry:
        retry_job = enqueue_agent_job(
            workflow_name=f"retry:{target['node']}",
            payload_summary=f"Rollback retry {target['node']} for {workflow_id}",
            payload={
                "workflow_id": workflow_id,
                "step_id": target_step_id,
                "node": target["node"],
                "reviewer_id": reviewer_id,
                "rollback_reason": reason,
            },
            priority=90,
        )
    log_agent_event(
        "run",
        workflow_id,
        "RUN_ROLLED_BACK",
        reason,
        {
            "target_step_id": target_step_id,
            "node": target["node"],
            "reviewer_id": reviewer_id,
            "rolled_back_step_count": len(later_steps),
            "retry_job_id": retry_job["job_id"] if retry_job else None,
        },
    )
    return {
        "ok": True,
        "status": "ROLLED_BACK",
        "current_step": target["node"],
        "rolled_back_step_count": len(later_steps),
        "retry_job": retry_job,
    }


def log_agent_event(entity_type: str, entity_id: str, event_type: str, summary: str, payload: dict[str, Any] | None = None) -> None:
    _ensure_schema(create_events_only=True)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_events
            (event_id, entity_type, entity_id, event_type, summary, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (f"evt_{uuid4().hex[:12]}", entity_type, entity_id, event_type, summary, json.dumps(payload or {}, ensure_ascii=False), _now()),
        )


def list_agent_events(entity_type: str | None = None, entity_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    _ensure_schema()
    clauses: list[str] = []
    params: list[Any] = []
    if entity_type:
        clauses.append("entity_type = ?")
        params.append(entity_type)
    if entity_id:
        clauses.append("entity_id = ?")
        params.append(entity_id)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT event_id, entity_type, entity_id, event_type, summary, payload_json, created_at
            FROM agent_events
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        output.append(item)
    return output


def _ensure_schema(create_events_only: bool = False) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_events (
                event_id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        if create_events_only:
            return
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                workflow_id TEXT PRIMARY KEY,
                workflow_name TEXT NOT NULL,
                status TEXT NOT NULL,
                current_step TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_steps (
                step_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                node TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                max_attempts INTEGER NOT NULL,
                assigned_to TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                input_summary TEXT NOT NULL,
                output_summary TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_jobs (
                job_id TEXT PRIMARY KEY,
                workflow_name TEXT NOT NULL,
                status TEXT NOT NULL,
                priority INTEGER NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 2,
                payload_summary TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                assigned_to TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "agent_jobs", "attempts", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "agent_jobs", "max_attempts", "INTEGER NOT NULL DEFAULT 2")
        _ensure_column(conn, "agent_jobs", "last_error", "TEXT")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _next_attempt(workflow_id: str, node: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT MAX(attempt) AS attempt FROM agent_steps WHERE workflow_id = ? AND node = ?",
            (workflow_id, node),
        ).fetchone()
    return int(row["attempt"] or 0) + 1


def _run_status_for(status: AgentStatus) -> str:
    if status == AgentStatus.failed:
        return "FAILED"
    if status == AgentStatus.needs_human:
        return "NEEDS_HUMAN"
    return "RUNNING"


def _step_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["payload_json"] or "{}")
    output = dict(row)
    output["payload"] = payload
    output.pop("payload_json", None)
    return output


def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["payload_json"] or "{}")
    output = dict(row)
    output["worker_summary"] = payload.get("worker_summary")
    output["can_retry"] = bool(payload.get("can_retry"))
    output.pop("payload_json", None)
    return output


def _merge_payload(payload_json: str, patch: dict[str, Any]) -> str:
    payload = json.loads(payload_json or "{}")
    payload.update(patch)
    return json.dumps(payload, ensure_ascii=False)

from contextlib import closing


def _ensure_multi_agent_schema() -> None:
    """Create isolated tables for the supervisor runtime without replacing legacy jobs."""
    _ensure_schema()
    with closing(_connect()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS multi_agent_workflows (
                workflow_id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                owner_id TEXT,
                status TEXT NOT NULL,
                current_agent TEXT,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_checkpoints (
                checkpoint_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                state_schema_version TEXT NOT NULL,
                state_json TEXT NOT NULL,
                status TEXT NOT NULL,
                current_agent TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_trace_events (
                event_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                parent_event_id TEXT,
                event_type TEXT NOT NULL,
                agent_name TEXT,
                tool_name TEXT,
                tool_call_id TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_ms INTEGER,
                model TEXT,
                provider TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                cached_tokens INTEGER,
                total_tokens INTEGER,
                cost_usd REAL,
                input_summary TEXT,
                output_summary TEXT,
                error_type TEXT,
                error_message TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_usage (
                usage_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                trace_event_id TEXT NOT NULL,
                model TEXT,
                provider TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                cached_tokens INTEGER,
                total_tokens INTEGER,
                cost_usd REAL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def create_multi_agent_workflow(
    workflow_id: str,
    goal: str,
    state_json: dict[str, Any],
    *,
    owner_id: str | None = None,
) -> None:
    _ensure_multi_agent_schema()
    now = _now()
    payload = json.dumps(_redact_runtime_payload(state_json), ensure_ascii=False)
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO multi_agent_workflows
            (workflow_id, goal, owner_id, status, current_agent, state_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (workflow_id, goal, owner_id, str(state_json.get("status", "RUNNING")), state_json.get("current_agent"), payload, now, now),
        )
        conn.commit()


def update_multi_agent_workflow(state_json: dict[str, Any]) -> None:
    _ensure_multi_agent_schema()
    payload = json.dumps(_redact_runtime_payload(state_json), ensure_ascii=False)
    with closing(_connect()) as conn:
        conn.execute(
            """
            UPDATE multi_agent_workflows
            SET status = ?, current_agent = ?, state_json = ?, updated_at = ?
            WHERE workflow_id = ?
            """,
            (str(state_json.get("status", "RUNNING")), state_json.get("current_agent"), payload, _now(), state_json["workflow_id"]),
        )
        conn.commit()


def get_multi_agent_workflow(workflow_id: str) -> dict[str, Any] | None:
    _ensure_multi_agent_schema()
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM multi_agent_workflows WHERE workflow_id = ?", (workflow_id,)).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["state"] = json.loads(result.pop("state_json") or "{}")
    return result


def list_multi_agent_workflows(limit: int = 80) -> list[dict[str, Any]]:
    _ensure_multi_agent_schema()
    with closing(_connect()) as conn:
        rows = conn.execute(
            """SELECT workflow_id, goal, owner_id, status, current_agent, created_at, updated_at
            FROM multi_agent_workflows ORDER BY updated_at DESC LIMIT ?""",
            (max(1, min(limit, 200)),),
        ).fetchall()
    return [dict(row) for row in rows]


def _prune_checkpoint_history(
    conn: sqlite3.Connection,
    *,
    workflow_id: str,
    current_day: str,
) -> None:
    """Apply per-workflow, per-day and global checkpoint retention.

    Only checkpoint rows are removed here.  The current workflow row, business
    data, traces, jobs and source/evidence tables are intentionally untouched.
    The newest checkpoint for an active workflow is protected by the global
    cleanup pass so a running workflow can still resume.
    """

    max_per_workflow = max(1, int(CHECKPOINT_MAX_PER_WORKFLOW))
    daily_keep = max(1, int(CHECKPOINT_DAILY_KEEP))
    max_total = max(1, int(CHECKPOINT_MAX_TOTAL))

    rows = conn.execute(
        """
        SELECT checkpoint_id, substr(created_at, 1, 10) AS checkpoint_day, created_at
        FROM agent_checkpoints
        WHERE workflow_id = ?
        ORDER BY created_at DESC, checkpoint_id DESC
        """,
        (workflow_id,),
    ).fetchall()

    keep_ids: list[str] = []
    kept_by_day: dict[str, int] = {}
    for row in rows:
        day = str(row["checkpoint_day"] or "")
        day_limit = max_per_workflow if day == current_day else daily_keep
        if kept_by_day.get(day, 0) >= day_limit:
            continue
        keep_ids.append(str(row["checkpoint_id"]))
        kept_by_day[day] = kept_by_day.get(day, 0) + 1

    # The per-workflow cap wins over the per-day allowance when a workflow has
    # accumulated several historical days of snapshots.
    keep_ids = keep_ids[:max_per_workflow]
    keep_set = set(keep_ids)
    delete_ids = [str(row["checkpoint_id"]) for row in rows if str(row["checkpoint_id"]) not in keep_set]
    if delete_ids:
        conn.executemany(
            "DELETE FROM agent_checkpoints WHERE checkpoint_id = ?",
            [(checkpoint_id,) for checkpoint_id in delete_ids],
        )

    total = int(conn.execute("SELECT COUNT(*) FROM agent_checkpoints").fetchone()[0])
    excess = total - max_total
    if excess <= 0:
        return

    # Prefer deleting old history and terminal workflow snapshots.  Never
    # delete the newest checkpoint of an active workflow; if every workflow is
    # active and has only one row, the safety rule deliberately leaves the
    # count above the global cap rather than making an active workflow
    # unrecoverable.
    candidates = conn.execute(
        """
        SELECT c.checkpoint_id
        FROM agent_checkpoints AS c
        LEFT JOIN multi_agent_workflows AS w ON w.workflow_id = c.workflow_id
        WHERE c.status IN ('COMPLETED', 'FAILED')
           OR w.status IN ('COMPLETED', 'FAILED')
           OR EXISTS (
                SELECT 1
                FROM agent_checkpoints AS newer
                WHERE newer.workflow_id = c.workflow_id
                  AND (
                        newer.created_at > c.created_at
                        OR (newer.created_at = c.created_at AND newer.checkpoint_id > c.checkpoint_id)
                  )
           )
        ORDER BY c.created_at ASC, c.checkpoint_id ASC
        LIMIT ?
        """,
        (excess,),
    ).fetchall()
    if candidates:
        conn.executemany(
            "DELETE FROM agent_checkpoints WHERE checkpoint_id = ?",
            [(str(row["checkpoint_id"]),) for row in candidates],
        )


def save_workflow_checkpoint(
    *,
    workflow_id: str,
    state_schema_version: str,
    state_json: dict[str, Any],
    status: str,
    current_agent: str | None,
) -> str:
    _ensure_multi_agent_schema()
    checkpoint_id = f"ckpt_{uuid4().hex[:16]}"
    created_at = _now()
    payload = json.dumps(_redact_runtime_payload(state_json), ensure_ascii=False)
    with closing(_connect()) as conn:
        conn.execute(
            """INSERT INTO agent_checkpoints
            (checkpoint_id, workflow_id, state_schema_version, state_json, status, current_agent, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (checkpoint_id, workflow_id, state_schema_version, payload, status, current_agent, created_at),
        )
        conn.execute(
            """UPDATE multi_agent_workflows SET status = ?, current_agent = ?, state_json = ?, updated_at = ?
            WHERE workflow_id = ?""",
            (status, current_agent, payload, created_at, workflow_id),
        )
        _prune_checkpoint_history(
            conn,
            workflow_id=workflow_id,
            current_day=created_at[:10],
        )
        conn.commit()
    return checkpoint_id


def load_workflow_checkpoint(workflow_id: str) -> dict[str, Any] | None:
    _ensure_multi_agent_schema()
    with closing(_connect()) as conn:
        row = conn.execute(
            """SELECT checkpoint_id, workflow_id, state_schema_version, state_json, status, current_agent, created_at
            FROM agent_checkpoints WHERE workflow_id = ? ORDER BY created_at DESC LIMIT 1""",
            (workflow_id,),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["state"] = json.loads(result.pop("state_json") or "{}")
    return result


def record_runtime_trace_event(event: dict[str, Any]) -> None:
    _ensure_multi_agent_schema()
    # Trace rows are a persistence boundary too; sanitize before extracting
    # scalar columns so secrets cannot survive in summaries or diagnostics.
    event = sanitize_runtime_payload(event)
    fields = [
        "event_id", "workflow_id", "parent_event_id", "event_type", "agent_name", "tool_name", "tool_call_id",
        "started_at", "finished_at", "duration_ms", "model", "provider", "prompt_tokens", "completion_tokens",
        "cached_tokens", "total_tokens", "cost_usd", "input_summary", "output_summary", "error_type", "error_message",
    ]
    values = [event.get(field) for field in fields]
    with closing(_connect()) as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO runtime_trace_events ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
            values,
        )
        if event.get("total_tokens") is not None:
            conn.execute(
                """INSERT INTO llm_usage
                (usage_id, workflow_id, trace_event_id, model, provider, prompt_tokens, completion_tokens, cached_tokens, total_tokens, cost_usd, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"usage_{uuid4().hex[:16]}", event.get("workflow_id"), event.get("event_id"), event.get("model"),
                    event.get("provider"), event.get("prompt_tokens"), event.get("completion_tokens"), event.get("cached_tokens"),
                    event.get("total_tokens"), event.get("cost_usd"), _now(),
                ),
            )
        conn.commit()


def list_runtime_trace_events(workflow_id: str) -> list[dict[str, Any]]:
    _ensure_multi_agent_schema()
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM runtime_trace_events WHERE workflow_id = ? ORDER BY started_at ASC, event_id ASC",
            (workflow_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _redact_runtime_payload(value: Any) -> Any:
    """Backward-compatible wrapper around the shared recursive sanitizer."""

    return sanitize_runtime_payload(value)
