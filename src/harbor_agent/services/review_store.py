from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from harbor_agent.models import FieldEvidenceRecord
from harbor_agent.services.data_loader import DATA_DIR
from harbor_agent.services.program_store import (
    DB_PATH,
    load_field_evidence_records,
    upsert_field_evidence_records,
)

STORE_PATH = DATA_DIR / "reviewed_field_evidence.local.json"


def load_published_field_records() -> list[FieldEvidenceRecord]:
    """Load formal records only from the canonical SQLite evidence store."""

    try:
        persisted = [
            record
            for record in load_field_evidence_records(db_path=DB_PATH)
            if record.status.value == "OFFICIAL_VERIFIED_CURRENT" and not record.review_required
        ]
        return _dedupe_records(persisted)
    except Exception:
        return []


def save_published_field_record(record: FieldEvidenceRecord) -> None:
    upsert_field_evidence_records([record], db_path=DB_PATH)
    records = load_published_field_records()
    remaining = [
        item
        for item in records
        if not (
            item.program_id == record.program_id
            and item.field_name == record.field_name
            and item.cycle == record.cycle
        )
    ]
    remaining.append(record)
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = STORE_PATH.with_suffix(STORE_PATH.suffix + ".tmp")
    temp_path.write_text(
        json.dumps([item.model_dump(mode="json") for item in remaining], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(STORE_PATH)
    try:
        from harbor_agent.services.data_loader import clear_data_loader_caches

        clear_data_loader_caches()
    except Exception:
        pass


def save_review_decision(
    *,
    review_id: str,
    program_id: str,
    field_name: str,
    decision: str,
    reviewer_id: str,
    reviewer_note: str | None = None,
    db_path=None,
) -> str:
    decision_id = f"decision_{uuid4().hex[:14]}"
    with sqlite3.connect(db_path or DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS review_decisions (
                decision_id TEXT PRIMARY KEY,
                review_id TEXT NOT NULL,
                program_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                decision TEXT NOT NULL,
                reviewer_id TEXT NOT NULL,
                reviewer_note TEXT,
                decided_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO review_decisions
            (decision_id, review_id, program_id, field_name, decision, reviewer_id, reviewer_note, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                review_id,
                program_id,
                field_name,
                decision,
                reviewer_id,
                reviewer_note,
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
    return decision_id


def load_review_decisions(*, db_path=None) -> dict[str, str]:
    try:
        with sqlite3.connect(db_path or DB_PATH) as conn:
            rows = conn.execute(
                "SELECT review_id, decision FROM review_decisions ORDER BY decided_at, rowid"
            ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {str(review_id): str(decision) for review_id, decision in rows}


def _dedupe_records(records: list[FieldEvidenceRecord]) -> list[FieldEvidenceRecord]:
    by_key: dict[tuple[str, str, str | None], FieldEvidenceRecord] = {}
    for record in records:
        by_key[(record.program_id, record.field_name, record.cycle)] = record
    return list(by_key.values())
