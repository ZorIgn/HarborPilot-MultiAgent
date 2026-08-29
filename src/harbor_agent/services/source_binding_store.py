from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from harbor_agent.services import program_store


def save_program_source_binding(
    *,
    workflow_id: str,
    program_id: str,
    source_url: str,
    field_names: list[str],
    page_hash: str | None,
    approval_id: str,
    reviewer_id: str,
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Idempotently persist an approved source-to-program binding."""

    if not str(page_hash or "").strip() or not str(snapshot_id or "").strip():
        raise ValueError("a source binding must include the exact snapshot_id and page_hash")

    normalized_fields = sorted(dict.fromkeys(str(item) for item in field_names if item))
    identity = json.dumps(
        {
            "workflow_id": workflow_id,
            "program_id": program_id,
            "source_url": source_url,
            "field_names": normalized_fields,
            "page_hash": page_hash,
            "snapshot_id": snapshot_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    binding_id = "binding_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    created_at = datetime.now(UTC).isoformat()
    with sqlite3.connect(program_store.DB_PATH, timeout=10) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS program_source_bindings (
                binding_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                program_id TEXT NOT NULL,
                source_url TEXT NOT NULL,
                field_names_json TEXT NOT NULL,
                page_hash TEXT,
                snapshot_id TEXT,
                approval_id TEXT NOT NULL,
                reviewer_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "program_source_bindings", "snapshot_id", "TEXT")
        conn.execute(
            """
            INSERT INTO program_source_bindings (
                binding_id, workflow_id, program_id, source_url, field_names_json,
                page_hash, snapshot_id, approval_id, reviewer_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(binding_id) DO UPDATE SET
                approval_id = excluded.approval_id,
                reviewer_id = excluded.reviewer_id
            """,
            (
                binding_id,
                workflow_id,
                program_id,
                source_url,
                json.dumps(normalized_fields, ensure_ascii=False),
                page_hash,
                snapshot_id,
                approval_id,
                reviewer_id,
                created_at,
            ),
        )
        conn.commit()
    return {
        "binding_id": binding_id,
        "workflow_id": workflow_id,
        "program_id": program_id,
        "source_url": source_url,
        "field_names": normalized_fields,
        "page_hash": page_hash,
        "snapshot_id": snapshot_id,
        "approval_id": approval_id,
        "reviewer_id": reviewer_id,
        "created_at": created_at,
        "persisted": True,
    }


def load_program_source_binding(
    *,
    workflow_id: str,
    program_id: str,
    source_url: str,
) -> dict[str, Any] | None:
    try:
        with sqlite3.connect(program_store.DB_PATH, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM program_source_bindings
                WHERE workflow_id = ? AND program_id = ? AND source_url = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (workflow_id, program_id, source_url),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    return {
        "binding_id": str(row["binding_id"]),
        "workflow_id": str(row["workflow_id"]),
        "program_id": str(row["program_id"]),
        "source_url": str(row["source_url"]),
        "field_names": json.loads(str(row["field_names_json"])),
        "page_hash": row["page_hash"],
        "snapshot_id": row["snapshot_id"] if "snapshot_id" in row.keys() else None,
        "approval_id": str(row["approval_id"]),
        "reviewer_id": str(row["reviewer_id"]),
        "created_at": str(row["created_at"]),
        "persisted": True,
    }


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
