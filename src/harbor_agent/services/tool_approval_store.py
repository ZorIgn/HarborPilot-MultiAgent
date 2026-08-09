from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from harbor_agent.runtime.approval import ToolApprovalRecord
from harbor_agent.runtime.errors import ToolPermissionError
from harbor_agent.services import agent_runtime

_APPROVAL_TTL = timedelta(minutes=30)


def create_pending_tool_approval(
    *,
    workflow_id: str,
    agent_name: str,
    tool_name: str,
    tool_call_id: str,
    arguments: dict,
    arguments_json: str,
    arguments_sha256: str,
) -> ToolApprovalRecord:
    """Persist or return the pending request for this exact call."""

    now = datetime.now(UTC)
    expires_at = now + _APPROVAL_TTL
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE runtime_tool_approvals
            SET status = 'REJECTED', rejected_at = ?, reviewer_note = 'expired automatically'
            WHERE status IN ('PENDING', 'APPROVED') AND expires_at <= ?
            """,
            (now.isoformat(), now.isoformat()),
        )
        row = conn.execute(
            """
            SELECT * FROM runtime_tool_approvals
            WHERE workflow_id = ? AND agent_name = ? AND tool_name = ?
              AND arguments_sha256 = ? AND status = 'PENDING' AND expires_at > ?
            ORDER BY requested_at DESC LIMIT 1
            """,
            (workflow_id, agent_name, tool_name, arguments_sha256, now.isoformat()),
        ).fetchone()
        if row is not None:
            conn.commit()
            return _record(row)
        approval_id = f"approval_{uuid4().hex[:20]}"
        conn.execute(
            """
            INSERT INTO runtime_tool_approvals (
                approval_id, workflow_id, agent_name, tool_name, tool_call_id,
                arguments_json, arguments_sha256, status, requested_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
            """,
            (
                approval_id,
                workflow_id,
                agent_name,
                tool_name,
                tool_call_id,
                arguments_json,
                arguments_sha256,
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )
        conn.commit()
    return ToolApprovalRecord(
        approval_id=approval_id,
        workflow_id=workflow_id,
        agent_name=agent_name,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        arguments=arguments,
        arguments_sha256=arguments_sha256,
        status="PENDING",
        requested_at=now,
        expires_at=expires_at,
    )


def approve_tool_approval(
    approval_id: str,
    *,
    workflow_id: str,
    reviewer_id: str,
    reviewer_note: str | None = None,
) -> ToolApprovalRecord:
    now = datetime.now(UTC)
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM runtime_tool_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        record = _require_record(row, approval_id)
        if record.workflow_id != workflow_id:
            raise ToolPermissionError("tool approval belongs to a different workflow")
        if record.status != "PENDING":
            raise ToolPermissionError(f"tool approval is {record.status.lower()}, not pending")
        if record.expires_at <= now:
            raise ToolPermissionError("tool approval request has expired")
        conn.execute(
            """
            UPDATE runtime_tool_approvals
            SET status = 'APPROVED', reviewer_id = ?, reviewer_note = ?, approved_at = ?
            WHERE approval_id = ? AND status = 'PENDING'
            """,
            (reviewer_id, reviewer_note, now.isoformat(), approval_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM runtime_tool_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
    return _require_record(row, approval_id)


def reject_tool_approval(
    approval_id: str,
    *,
    workflow_id: str,
    reviewer_id: str,
    reviewer_note: str | None = None,
) -> ToolApprovalRecord:
    now = datetime.now(UTC)
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM runtime_tool_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        record = _require_record(row, approval_id)
        if record.workflow_id != workflow_id:
            raise ToolPermissionError("tool approval belongs to a different workflow")
        if record.status != "PENDING":
            raise ToolPermissionError(f"tool approval is {record.status.lower()}, not pending")
        conn.execute(
            """
            UPDATE runtime_tool_approvals
            SET status = 'REJECTED', reviewer_id = ?, reviewer_note = ?, rejected_at = ?
            WHERE approval_id = ? AND status = 'PENDING'
            """,
            (reviewer_id, reviewer_note, now.isoformat(), approval_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM runtime_tool_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
    return _require_record(row, approval_id)


def consume_tool_approval(
    approval_id: str,
    *,
    workflow_id: str,
    agent_name: str,
    tool_name: str,
    tool_call_id: str,
    arguments_sha256: str,
) -> ToolApprovalRecord:
    """Atomically consume an exact grant before the mutating handler runs."""

    now = datetime.now(UTC)
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM runtime_tool_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        record = _require_record(row, approval_id)
        expected = (
            record.workflow_id,
            record.agent_name,
            record.tool_name,
            record.tool_call_id,
            record.arguments_sha256,
        )
        actual = (workflow_id, agent_name, tool_name, tool_call_id, arguments_sha256)
        if expected != actual:
            raise ToolPermissionError("tool approval does not match this workflow, agent, call, or arguments")
        if record.status != "APPROVED":
            raise ToolPermissionError(f"tool approval is {record.status.lower()}, not approved")
        if record.expires_at <= now:
            raise ToolPermissionError("tool approval has expired")
        updated = conn.execute(
            """
            UPDATE runtime_tool_approvals
            SET status = 'CONSUMED', consumed_at = ?
            WHERE approval_id = ? AND status = 'APPROVED'
            """,
            (now.isoformat(), approval_id),
        )
        if updated.rowcount != 1:
            raise ToolPermissionError("tool approval was already consumed")
        conn.commit()
        row = conn.execute(
            "SELECT * FROM runtime_tool_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
    return _require_record(row, approval_id)


def get_tool_approval(approval_id: str) -> ToolApprovalRecord | None:
    with _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM runtime_tool_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
    return _record(row) if row is not None else None


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(agent_runtime.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_tool_approvals (
            approval_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            tool_call_id TEXT NOT NULL,
            arguments_json TEXT NOT NULL,
            arguments_sha256 TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED','CONSUMED')),
            reviewer_id TEXT,
            reviewer_note TEXT,
            requested_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            approved_at TEXT,
            rejected_at TEXT,
            consumed_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_runtime_tool_approval_lookup
        ON runtime_tool_approvals(workflow_id, agent_name, tool_name, arguments_sha256, status)
        """
    )
    conn.execute(
        """
        UPDATE runtime_tool_approvals
        SET status = 'REJECTED', reviewer_note = 'superseded during approval migration'
        WHERE status IN ('PENDING', 'APPROVED') AND rowid NOT IN (
            SELECT MIN(rowid) FROM runtime_tool_approvals
            WHERE status IN ('PENDING', 'APPROVED')
            GROUP BY workflow_id, agent_name, tool_name, arguments_sha256
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_tool_approval_active_exact
        ON runtime_tool_approvals(workflow_id, agent_name, tool_name, arguments_sha256)
        WHERE status IN ('PENDING', 'APPROVED')
        """
    )
    conn.commit()


def _require_record(row: sqlite3.Row | None, approval_id: str) -> ToolApprovalRecord:
    if row is None:
        raise ToolPermissionError(f"tool approval not found: {approval_id}")
    return _record(row)


def _record(row: sqlite3.Row) -> ToolApprovalRecord:
    return ToolApprovalRecord(
        approval_id=str(row["approval_id"]),
        workflow_id=str(row["workflow_id"]),
        agent_name=str(row["agent_name"]),
        tool_name=str(row["tool_name"]),
        tool_call_id=str(row["tool_call_id"]),
        arguments=json.loads(str(row["arguments_json"])),
        arguments_sha256=str(row["arguments_sha256"]),
        status=str(row["status"]),
        reviewer_id=row["reviewer_id"],
        reviewer_note=row["reviewer_note"],
        requested_at=datetime.fromisoformat(str(row["requested_at"])),
        expires_at=datetime.fromisoformat(str(row["expires_at"])),
        approved_at=datetime.fromisoformat(str(row["approved_at"])) if row["approved_at"] else None,
        rejected_at=datetime.fromisoformat(str(row["rejected_at"])) if row["rejected_at"] else None,
        consumed_at=datetime.fromisoformat(str(row["consumed_at"])) if row["consumed_at"] else None,
    )
