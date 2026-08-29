from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from harbor_agent.models import (
    FieldEvidenceRecord,
    FieldVerificationStatus,
    Program,
    ProgramFieldEvidence,
)

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "harborpilot.sqlite3"
PROGRAM_JSON = DATA_DIR / "programs_2027_fall.json"
PROGRAM_URL_OVERRIDES = DATA_DIR / "program_url_overrides.json"
INSTITUTION_APPLICATION_PORTALS = DATA_DIR / "institution_application_portals.json"


def _clear_data_loader_caches_after_write() -> None:
    try:
        from harbor_agent.services.data_loader import clear_data_loader_caches

        clear_data_loader_caches()
    except Exception:
        # Cache invalidation should not make persistence fail; the next process will read fresh storage.
        pass


def init_program_store(db_path: Path | None = None) -> None:
    db_path = db_path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS program_catalog (
                id TEXT PRIMARY KEY,
                institution TEXT NOT NULL,
                institution_zh TEXT,
                school TEXT NOT NULL,
                school_zh TEXT,
                program_name TEXT NOT NULL,
                program_name_zh TEXT,
                degree_type TEXT NOT NULL,
                region TEXT NOT NULL,
                direction_json TEXT NOT NULL,
                duration_months INTEGER NOT NULL,
                tuition_hkd INTEGER,
                application_fee_hkd INTEGER,
                application_url TEXT,
                official_program_url TEXT,
                language_requirement_json TEXT NOT NULL,
                prerequisites_json TEXT NOT NULL,
                materials_json TEXT NOT NULL,
                rounds_json TEXT NOT NULL,
                open_date TEXT,
                deadline TEXT NOT NULL,
                essay_prompts_json TEXT NOT NULL,
                source_evidence_json TEXT NOT NULL,
                data_status TEXT NOT NULL,
                last_verified_at TEXT,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS program_field_evidence (
                id TEXT PRIMARY KEY,
                program_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                value TEXT,
                cycle TEXT,
                source_url TEXT,
                source_type TEXT NOT NULL,
                extracted_at TEXT,
                verified_at TEXT,
                page_hash TEXT,
                confidence TEXT NOT NULL,
                source_priority INTEGER NOT NULL,
                status TEXT NOT NULL,
                review_required INTEGER NOT NULL,
                reviewer_id TEXT,
                evidence_snippet TEXT,
                snapshot_url TEXT,
                execution_ref_json TEXT,
                source_scope TEXT,
                page_title TEXT,
                final_url TEXT,
                binding_status TEXT NOT NULL DEFAULT 'not_checked',
                binding_score INTEGER NOT NULL DEFAULT 0,
                reviewer_note TEXT,
                review_decision_id TEXT,
                agent_chain_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(program_id) REFERENCES program_catalog(id)
            )
            """
        )
        _ensure_column(conn, "program_field_evidence", "source_scope", "TEXT")
        _ensure_column(conn, "program_field_evidence", "page_title", "TEXT")
        _ensure_column(conn, "program_field_evidence", "final_url", "TEXT")
        _ensure_column(conn, "program_field_evidence", "binding_status", "TEXT NOT NULL DEFAULT 'not_checked'")
        _ensure_column(conn, "program_field_evidence", "execution_ref_json", "TEXT")
        _ensure_column(conn, "program_field_evidence", "binding_score", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "program_field_evidence", "reviewer_note", "TEXT")
        _ensure_column(conn, "program_field_evidence", "review_decision_id", "TEXT")
        # Older databases retain this NOT NULL compatibility column.  Keep an
        # empty value so new evidence writes never invent an agent chain while
        # remaining writable without a destructive table rebuild.
        _ensure_column(
            conn,
            "program_field_evidence",
            "agent_chain_json",
            "TEXT NOT NULL DEFAULT '[]'",
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_program_field_evidence_program ON program_field_evidence(program_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_program_field_evidence_field ON program_field_evidence(field_name)")
        conn.execute('CREATE INDEX IF NOT EXISTS idx_program_field_evidence_status ON program_field_evidence(status)')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_program_catalog_region ON program_catalog(region)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_program_catalog_institution ON program_catalog(institution)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS program_store_metadata (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO program_store_metadata (key, value) VALUES ('catalog_revision', 0)"
        )
        conn.commit()


def load_programs_from_store(
    *,
    db_path: Path | None = None,
    seed_json_path: Path = PROGRAM_JSON,
) -> list[Program]:
    db_path = db_path or DB_PATH
    init_program_store(db_path)
    if _program_count(db_path) == 0 and seed_json_path.exists():
        seed_program_store(_load_program_json(seed_json_path), db_path=db_path, replace=True)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT payload_json FROM program_catalog ORDER BY region, institution, school, program_name"
        ).fetchall()
    return apply_program_url_overrides([Program.model_validate_json(row[0]) for row in rows])


def seed_program_store(programs: Iterable[Program], *, db_path: Path | None = None, replace: bool = True) -> int:
    db_path = db_path or DB_PATH
    init_program_store(db_path)
    rows = [_program_row(program) for program in apply_program_url_overrides(list(programs))]
    sql = """
        INSERT OR REPLACE INTO program_catalog (
            id, institution, institution_zh, school, school_zh, program_name, program_name_zh,
            degree_type, region, direction_json, duration_months, tuition_hkd, application_fee_hkd,
            application_url, official_program_url, language_requirement_json, prerequisites_json,
            materials_json, rounds_json, open_date, deadline, essay_prompts_json,
            source_evidence_json, data_status, last_verified_at, payload_json
        )
        VALUES (
            :id, :institution, :institution_zh, :school, :school_zh, :program_name, :program_name_zh,
            :degree_type, :region, :direction_json, :duration_months, :tuition_hkd, :application_fee_hkd,
            :application_url, :official_program_url, :language_requirement_json, :prerequisites_json,
            :materials_json, :rounds_json, :open_date, :deadline, :essay_prompts_json,
            :source_evidence_json, :data_status, :last_verified_at, :payload_json
        )
    """
    with _connect(db_path) as conn:
        if replace:
            conn.execute("DELETE FROM program_catalog")
        conn.executemany(sql, rows)
        conn.execute(
            """
            UPDATE program_store_metadata
            SET value = value + 1, updated_at = CURRENT_TIMESTAMP
            WHERE key = 'catalog_revision'
            """
        )
        conn.commit()
    _clear_data_loader_caches_after_write()
    return len(rows)




def upsert_field_evidence_records(
    records: Iterable[FieldEvidenceRecord],
    *,
    db_path: Path | None = None,
) -> int:
    db_path = db_path or DB_PATH
    init_program_store(db_path)
    rows = [_field_evidence_row(record) for record in records]
    if not rows:
        return 0
    with _connect(db_path) as conn:
        _upsert_field_evidence_rows(conn, rows)
        conn.commit()
    _clear_data_loader_caches_after_write()
    return len(rows)


def _upsert_field_evidence_rows(conn: sqlite3.Connection, rows: list[dict[str, object]]) -> None:
    sql = """
        INSERT INTO program_field_evidence (
            id, program_id, field_name, value, cycle, source_url, source_type, extracted_at,
            verified_at, page_hash, confidence, source_priority, status, review_required,
            reviewer_id, evidence_snippet, snapshot_url, execution_ref_json,
            source_scope, page_title, final_url, binding_status, binding_score,
            reviewer_note, review_decision_id, agent_chain_json
        )
        VALUES (
            :id, :program_id, :field_name, :value, :cycle, :source_url, :source_type, :extracted_at,
            :verified_at, :page_hash, :confidence, :source_priority, :status, :review_required,
            :reviewer_id, :evidence_snippet, :snapshot_url, :execution_ref_json,
            :source_scope, :page_title, :final_url, :binding_status, :binding_score,
            :reviewer_note, :review_decision_id, :agent_chain_json
        )
        ON CONFLICT(id) DO UPDATE SET
            value=excluded.value,
            cycle=excluded.cycle,
            source_url=excluded.source_url,
            source_type=excluded.source_type,
            extracted_at=excluded.extracted_at,
            verified_at=excluded.verified_at,
            page_hash=excluded.page_hash,
            confidence=excluded.confidence,
            source_priority=excluded.source_priority,
            status=excluded.status,
            review_required=excluded.review_required,
            reviewer_id=excluded.reviewer_id,
            evidence_snippet=excluded.evidence_snippet,
            snapshot_url=excluded.snapshot_url,
            execution_ref_json=excluded.execution_ref_json,
            source_scope=excluded.source_scope,
            page_title=excluded.page_title,
            final_url=excluded.final_url,
            binding_status=excluded.binding_status,
            binding_score=excluded.binding_score,
            reviewer_note=excluded.reviewer_note,
            review_decision_id=excluded.review_decision_id,
            updated_at=CURRENT_TIMESTAMP
    """
    conn.executemany(sql, rows)


def persist_conflict_resolution(
    records: Iterable[FieldEvidenceRecord],
    *,
    action: str,
    conflict_id: str,
    reviewer_id: str,
    selected_record_id: str | None = None,
    reviewer_note: str | None = None,
    db_path: Path | None = None,
) -> tuple[FieldEvidenceRecord | None, str]:
    """Atomically apply one human conflict decision to evidence and its ledger.

    The caller supplies every member of the conflict group.  ``accept`` must
    name one durable ``evidence_id``/record ID from that set; that row becomes
    the sole current official row for its program/field/cycle and all sibling
    rows are superseded in the same SQLite transaction.  ``reject`` marks the
    supplied members as not published.  The review decision is written on the
    same connection, so a canonical resolver can never observe half of a
    decision.
    """

    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"accept", "reject"}:
        raise ValueError(f"unsupported conflict decision: {action}")
    if not str(conflict_id or "").strip():
        raise ValueError("conflict_id is required")
    if not str(reviewer_id or "").strip():
        raise ValueError("reviewer_id is required")
    members = list(records)
    if not members:
        raise ValueError("conflict resolution requires at least one evidence record")

    member_ids: list[str] = []
    normalized_members: list[FieldEvidenceRecord] = []
    for record in members:
        evidence_id = field_evidence_id(record)
        if evidence_id in member_ids:
            continue
        member_ids.append(evidence_id)
        normalized_members.append(record.model_copy(update={"evidence_id": evidence_id}))
    first = normalized_members[0]
    group_key = (first.program_id, first.field_name, first.cycle)
    if any(
        (record.program_id, record.field_name, record.cycle) != group_key
        for record in normalized_members[1:]
    ):
        raise ValueError("all conflict members must belong to the same program field and cycle")
    if normalized_action == "accept":
        if not selected_record_id:
            raise ValueError("accept requires selected_record_id")
        if str(selected_record_id) not in member_ids:
            raise ValueError("selected_record_id must identify a member evidence record")
        if str(selected_record_id) == str(conflict_id) and str(conflict_id).startswith(("conflict_", "fact_conflict_")):
            raise ValueError("selected_record_id must be a durable evidence record ID, not the conflict ID")
    elif selected_record_id:
        raise ValueError("reject applies to the whole conflict group and cannot select a record")

    db_path = db_path or DB_PATH
    init_program_store(db_path)
    decision_id = f"decision_{uuid4().hex[:14]}"
    decided_at = datetime.now(UTC)
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
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
        _upsert_field_evidence_rows(conn, [_field_evidence_row(record) for record in normalized_members])
        conn.execute(
            """
            INSERT INTO review_decisions
            (decision_id, review_id, program_id, field_name, decision, reviewer_id, reviewer_note, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                str(conflict_id),
                first.program_id,
                first.field_name,
                normalized_action,
                reviewer_id,
                reviewer_note,
                decided_at.isoformat(),
            ),
        )
        if normalized_action == "accept":
            selected = next(record for record in normalized_members if field_evidence_id(record) == str(selected_record_id))
            # Supersede every sibling in the same current programme field.  A
            # prior reviewer decision is intentionally replaced only inside
            # this transaction, never by a second out-of-band upsert.
            cycle_clause = "cycle = ?" if selected.cycle is not None else "cycle IS NULL"
            cycle_params: tuple[object, ...] = (selected.cycle,) if selected.cycle is not None else ()
            conn.execute(
                f"""
                UPDATE program_field_evidence
                SET status = 'NOT_PUBLISHED', review_required = 0,
                    reviewer_id = ?, reviewer_note = ?, review_decision_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE program_id = ? AND field_name = ? AND {cycle_clause}
                  AND id <> ?
                """,
                (
                    reviewer_id,
                    reviewer_note or f"superseded by accepted evidence record {selected_record_id}",
                    decision_id,
                    selected.program_id,
                    selected.field_name,
                    *cycle_params,
                    str(selected_record_id),
                ),
            )
            conn.execute(
                """
                UPDATE program_field_evidence
                SET status = 'OFFICIAL_VERIFIED_CURRENT', review_required = 0,
                    reviewer_id = ?, reviewer_note = ?, review_decision_id = ?,
                    verified_at = ?, confidence = 'high', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    reviewer_id,
                    reviewer_note,
                    decision_id,
                    decided_at.isoformat(),
                    str(selected_record_id),
                ),
            )
            result = selected.model_copy(
                update={
                    "status": FieldVerificationStatus.official_verified_current,
                    "review_required": False,
                    "reviewer_id": reviewer_id,
                    "reviewer_note": reviewer_note,
                    "review_decision_id": decision_id,
                    "verified_at": decided_at,
                    "confidence": "high",
                }
            )
        else:
            placeholders = ",".join("?" for _ in member_ids)
            conn.execute(
                f"""
                UPDATE program_field_evidence
                SET status = 'NOT_PUBLISHED', review_required = 0,
                    reviewer_id = ?, reviewer_note = ?, review_decision_id = ?,
                    verified_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})
                """,
                (
                    reviewer_id,
                    reviewer_note,
                    decision_id,
                    decided_at.isoformat(),
                    *member_ids,
                ),
            )
            result = normalized_members[0].model_copy(
                update={
                    "status": FieldVerificationStatus.not_published,
                    "review_required": False,
                    "reviewer_id": reviewer_id,
                    "reviewer_note": reviewer_note,
                    "review_decision_id": decision_id,
                    "verified_at": decided_at,
                }
            )
        conn.commit()
    _clear_data_loader_caches_after_write()
    return result, decision_id


def load_field_evidence_records(
    program_ids: Iterable[str] | None = None,
    *,
    db_path: Path | None = None,
) -> list[FieldEvidenceRecord]:
    db_path = db_path or DB_PATH
    init_program_store(db_path)
    params: list[str] = []
    where = ""
    if program_ids:
        ids = list(dict.fromkeys(program_ids))
        placeholders = ",".join("?" for _ in ids)
        where = f"WHERE program_id IN ({placeholders})"
        params.extend(ids)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT id, program_id, field_name, value, cycle, source_url, source_type, extracted_at,
                   verified_at, page_hash, confidence, source_priority, status, review_required,
                   reviewer_id, evidence_snippet, snapshot_url, execution_ref_json,
                   source_scope, page_title, final_url, binding_status, binding_score,
                   reviewer_note, review_decision_id
            FROM program_field_evidence
            {where}
            ORDER BY program_id, source_priority, field_name, updated_at DESC
            """,
            params,
        ).fetchall()
    return [_field_evidence_record_from_row(row) for row in rows]
def _program_count(db_path: Path) -> int:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM program_catalog").fetchone()
    return int(row[0] if row else 0)


def _load_program_json(path: Path) -> list[Program]:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return apply_program_url_overrides([Program.model_validate(item) for item in raw])



def apply_program_url_overrides(
    programs: list[Program],
    overrides_path: Path = PROGRAM_URL_OVERRIDES,
    portals_path: Path = INSTITUTION_APPLICATION_PORTALS,
) -> list[Program]:
    raw = []
    if overrides_path.exists():
        with overrides_path.open("r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
    portal_raw = []
    if portals_path.exists():
        with portals_path.open("r", encoding="utf-8-sig") as handle:
            portal_raw = json.load(handle)

    overrides = {item["program_id"]: item for item in raw}
    portals = {
        _normalize_institution_key(item.get("institution")): item
        for item in portal_raw
        if item.get("institution")
    }
    portals.update(
        {
            _normalize_institution_key(item.get("institution_zh")): item
            for item in portal_raw
            if item.get("institution_zh")
        }
    )

    updated: list[Program] = []
    for program in programs:
        override = overrides.get(program.id)
        portal = portals.get(_normalize_institution_key(program.institution)) or portals.get(
            _normalize_institution_key(program.institution_zh)
        )
        if not override and not portal:
            updated.append(program)
            continue

        evidence = dict(program.field_evidence)
        application_url = (override or {}).get("application_url") or (portal or {}).get("application_url")
        for field_name, value in {
            "official_program_url": (override or {}).get("official_program_url"),
            "application_url": application_url,
        }.items():
            if not value:
                continue
            source = portal if field_name == "application_url" and portal else override
            evidence[field_name] = ProgramFieldEvidence.model_validate(
                {
                    "field_name": field_name,
                    "value": value,
                    "cycle": (source or {}).get("cycle") or program.cycle,
                    "official_url": value,
                    "source_type": (source or {}).get("source_type")
                    or ("official_application_system" if field_name == "application_url" else "official_program_page"),
                    "excerpt": (source or {}).get("evidence_snippet")
                    or "官方来源入口已定位；关键申请字段仍需字段级核验。",
                    "captured_at": (source or {}).get("captured_at") or program.source.captured_at,
                    "verified_at": None,
                    "confidence": "medium",
                    "status": "EXTRACTED",
                }
            )

        updated.append(
            program.model_copy(
                update={
                    "official_program_url": (override or {}).get("official_program_url") or program.official_program_url,
                    "application_url": application_url or program.application_url,
                    "field_evidence": evidence,
                },
                deep=True,
            )
        )
    return updated


def _normalize_institution_key(value: str | None) -> str:
    return (value or "").strip().lower()
def _program_row(program: Program) -> dict[str, object]:
    evidence = [record.model_dump(mode="json") for record in program.field_evidence.values()]
    rounds = [
        {
            "round": item.name,
            "open_date": item.open_date.isoformat() if item.open_date else None,
            "deadline": item.deadline.isoformat() if item.deadline else "NOT_PUBLISHED",
            "applicant_scope": item.applicant_scope,
            "source": program.official_program_url or program.source.url,
            "status": program.data_status.value,
        }
        for item in program.application_rounds
    ]
    return {
        "id": program.id,
        "institution": program.institution,
        "institution_zh": program.institution_zh,
        "school": program.school,
        "school_zh": program.school_zh,
        "program_name": program.name,
        "program_name_zh": program.name_zh,
        "degree_type": program.degree_type,
        "region": program.country,
        "direction_json": json.dumps(program.discipline_tags, ensure_ascii=False),
        "duration_months": program.duration_months,
        "tuition_hkd": program.tuition_hkd,
        "application_fee_hkd": program.application_fee_hkd,
        "application_url": str(program.application_url) if program.application_url else None,
        "official_program_url": str(program.official_program_url) if program.official_program_url else None,
        "language_requirement_json": json.dumps(program.requirements.language, ensure_ascii=False),
        "prerequisites_json": json.dumps(program.requirements.prerequisites, ensure_ascii=False),
        "materials_json": json.dumps(program.materials, ensure_ascii=False),
        "rounds_json": json.dumps(rounds, ensure_ascii=False),
        "open_date": program.open_date.isoformat() if program.open_date else None,
        "deadline": str(program.deadline),
        "essay_prompts_json": json.dumps([], ensure_ascii=False),
        "source_evidence_json": json.dumps(evidence, ensure_ascii=False),
        "data_status": program.data_status.value,
        "last_verified_at": program.last_verified_at.isoformat() if program.last_verified_at else None,
        "payload_json": program.model_dump_json(),
    }


def _field_evidence_row(record: FieldEvidenceRecord) -> dict[str, object]:
    dumped = record.model_dump(mode="json")
    record_id = record.evidence_id or _field_evidence_id(record)
    return {
        "id": record_id,
        "program_id": record.program_id,
        "field_name": record.field_name,
        "value": record.value,
        "cycle": record.cycle,
        "source_url": str(record.source_url) if record.source_url else None,
        "source_type": record.source_type,
        "extracted_at": dumped.get("extracted_at"),
        "verified_at": dumped.get("verified_at"),
        "page_hash": record.page_hash,
        "confidence": record.confidence,
        "source_priority": record.source_priority,
        "status": record.status.value,
        "review_required": 1 if record.review_required else 0,
        "reviewer_id": record.reviewer_id,
        "evidence_snippet": record.evidence_snippet,
        "snapshot_url": str(record.snapshot_url) if record.snapshot_url else None,
        "execution_ref_json": json.dumps(record.execution_ref.model_dump(mode="json") if record.execution_ref else None, ensure_ascii=False),
        "source_scope": record.source_scope.value if record.source_scope else None,
        "page_title": record.page_title,
        "final_url": str(record.final_url) if record.final_url else None,
        "binding_status": record.binding_status,
        "binding_score": record.binding_score,
        "reviewer_note": record.reviewer_note,
        "review_decision_id": record.review_decision_id,
        "agent_chain_json": "[]",
    }


def _field_evidence_id(record: FieldEvidenceRecord) -> str:
    raw = "|".join(
        [
            record.program_id,
            record.field_name,
            record.cycle or "",
            str(record.source_url or ""),
            record.page_hash or "",
            record.value or "",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def field_evidence_id(record: FieldEvidenceRecord) -> str:
    """Return the durable SQLite identity used for one evidence row."""

    return str(record.evidence_id or _field_evidence_id(record))


def _field_evidence_record_from_row(row: tuple) -> FieldEvidenceRecord:
    return FieldEvidenceRecord(
        evidence_id=row[0],
        program_id=row[1],
        field_name=row[2],
        value=row[3],
        cycle=row[4],
        source_url=row[5],
        source_type=row[6],
        extracted_at=row[7],
        verified_at=row[8],
        page_hash=row[9],
        confidence=row[10],
        source_priority=row[11],
        status=FieldVerificationStatus(row[12]),
        review_required=bool(row[13]),
        reviewer_id=row[14],
        evidence_snippet=row[15],
        snapshot_url=row[16],
        execution_ref=json.loads(row[17]) if row[17] else None,
        source_scope=row[18] if row[18] else None,
        page_title=row[19],
        final_url=row[20],
        binding_status=row[21] or "not_checked",
        binding_score=int(row[22] or 0),
        reviewer_note=row[23],
        review_decision_id=row[24],
    )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def program_catalog_revision(db_path: Path | None = None) -> int:
    """Return a monotonic catalog revision for reliable cross-process cache invalidation."""
    db_path = db_path or DB_PATH
    init_program_store(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM program_store_metadata WHERE key = 'catalog_revision'"
        ).fetchone()
    return int(row[0]) if row else 0


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
