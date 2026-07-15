from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harbor_agent.config import get_settings
from harbor_agent.models import ApplicantProfileInput

ROOT = Path(__file__).resolve().parents[3]
DB_PATH = ROOT / "data" / "harborpilot.sqlite3"
DEFAULT_PROFILE_ID = "local_student"
PROTECTED_PREFIX = "hp1:"


def init_profile_store(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS student_profiles (
                profile_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS student_workspace_state (
                profile_id TEXT PRIMARY KEY,
                selected_program_ids_json TEXT NOT NULL,
                questionnaire_values_json TEXT NOT NULL,
                result_snapshot_json TEXT,
                field_sensitivity_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(student_workspace_state)").fetchall()}
        if "program_scheme_json" not in columns:
            conn.execute("ALTER TABLE student_workspace_state ADD COLUMN program_scheme_json TEXT")
        if "writing_draft_history_json" not in columns:
            conn.execute("ALTER TABLE student_workspace_state ADD COLUMN writing_draft_history_json TEXT")
        conn.commit()


def load_profile(profile_id: str = DEFAULT_PROFILE_ID, db_path: Path = DB_PATH) -> ApplicantProfileInput | None:
    init_profile_store(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM student_profiles WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()
    if row is None:
        return None
    payload_json = _unprotect_json(row[0], db_path)
    return ApplicantProfileInput.model_validate_json(payload_json)


def save_profile(
    profile: ApplicantProfileInput,
    profile_id: str = DEFAULT_PROFILE_ID,
    db_path: Path = DB_PATH,
) -> ApplicantProfileInput:
    init_profile_store(db_path)
    now = datetime.now(timezone.utc).isoformat()
    payload_json = profile.model_dump_json()
    stored_payload = _protect_json(payload_json, db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO student_profiles (profile_id, payload_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (profile_id, stored_payload, now, now),
        )
        conn.commit()
    return ApplicantProfileInput.model_validate(json.loads(payload_json))


DEFAULT_PROGRAM_SCHEME: dict[str, Any] = {
    "band_overrides": {},
    "removed_program_ids": [],
    "extra_candidate_ids": [],
}


DEFAULT_FIELD_SENSITIVITY: dict[str, str] = {
    "profile.personal_info": "sensitive_personal_context",
    "profile.education": "academic_record",
    "profile.language": "academic_record",
    "profile.experiences": "application_material",
    "profile.additional_background": "application_material",
    "selected_program_ids": "student_choice",
    "questionnaire_values": "sensitive_writing_material",
    "result_snapshot": "derived_application_work",
    "writing_draft_history": "derived_writing_work",
}


def load_workspace_state(
    profile_id: str = DEFAULT_PROFILE_ID,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    init_profile_store(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT selected_program_ids_json, questionnaire_values_json, result_snapshot_json, field_sensitivity_json, program_scheme_json, writing_draft_history_json
            FROM student_workspace_state
            WHERE profile_id = ?
            """,
            (profile_id,),
        ).fetchone()
    if row is None:
        return {
            "selected_program_ids": [],
            "questionnaire_values": {},
            "result_snapshot": None,
            "field_sensitivity": DEFAULT_FIELD_SENSITIVITY,
            "program_scheme": DEFAULT_PROGRAM_SCHEME,
            "writing_draft_history": [],
        }
    selected_json, questionnaire_json, result_json, sensitivity_json, program_scheme_json, writing_history_json = row
    return {
        "selected_program_ids": json.loads(_unprotect_json(selected_json, db_path)),
        "questionnaire_values": json.loads(_unprotect_json(questionnaire_json, db_path)),
        "result_snapshot": json.loads(_unprotect_json(result_json, db_path)) if result_json else None,
        "field_sensitivity": json.loads(_unprotect_json(sensitivity_json, db_path)),
        "program_scheme": _normalize_program_scheme(
            json.loads(_unprotect_json(program_scheme_json, db_path)) if program_scheme_json else DEFAULT_PROGRAM_SCHEME
        ),
        "writing_draft_history": _normalize_writing_draft_history(
            json.loads(_unprotect_json(writing_history_json, db_path)) if writing_history_json else []
        ),
    }


def save_workspace_state(
    selected_program_ids: list[str],
    questionnaire_values: dict[str, str],
    result_snapshot: dict[str, Any] | None = None,
    program_scheme: dict[str, Any] | None = None,
    writing_draft_history: list[dict[str, Any]] | None = None,
    profile_id: str = DEFAULT_PROFILE_ID,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    init_profile_store(db_path)
    now = datetime.now(timezone.utc).isoformat()
    selected_json = json.dumps(list(dict.fromkeys(selected_program_ids)), ensure_ascii=False)
    questionnaire_json = json.dumps(questionnaire_values, ensure_ascii=False)
    result_json = json.dumps(result_snapshot, ensure_ascii=False) if result_snapshot is not None else None
    sensitivity_json = json.dumps(DEFAULT_FIELD_SENSITIVITY, ensure_ascii=False)
    program_scheme_json = json.dumps(_normalize_program_scheme(program_scheme), ensure_ascii=False)
    writing_history_json = json.dumps(_normalize_writing_draft_history(writing_draft_history), ensure_ascii=False)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO student_workspace_state (
                profile_id,
                selected_program_ids_json,
                questionnaire_values_json,
                result_snapshot_json,
                field_sensitivity_json,
                program_scheme_json,
                writing_draft_history_json,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
                selected_program_ids_json = excluded.selected_program_ids_json,
                questionnaire_values_json = excluded.questionnaire_values_json,
                result_snapshot_json = excluded.result_snapshot_json,
                field_sensitivity_json = excluded.field_sensitivity_json,
                program_scheme_json = excluded.program_scheme_json,
                writing_draft_history_json = excluded.writing_draft_history_json,
                updated_at = excluded.updated_at
            """,
            (
                profile_id,
                _protect_json(selected_json, db_path),
                _protect_json(questionnaire_json, db_path),
                _protect_json(result_json, db_path) if result_json is not None else None,
                _protect_json(sensitivity_json, db_path),
                _protect_json(program_scheme_json, db_path),
                _protect_json(writing_history_json, db_path),
                now,
                now,
            ),
        )
        conn.commit()
    return load_workspace_state(profile_id=profile_id, db_path=db_path)



def _normalize_program_scheme(value: dict[str, Any] | None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    band_overrides = raw.get("band_overrides") if isinstance(raw.get("band_overrides"), dict) else {}
    valid_bands = {"reach", "target", "safe", "candidate", "blocked"}
    return {
        "band_overrides": {
            str(program_id): str(band)
            for program_id, band in band_overrides.items()
            if str(program_id).strip() and str(band) in valid_bands
        },
        "removed_program_ids": _unique_string_list(raw.get("removed_program_ids")),
        "extra_candidate_ids": _unique_string_list(raw.get("extra_candidate_ids")),
    }


def _normalize_writing_draft_history(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    output: list[dict[str, Any]] = []
    for item in value[:12]:
        if not isinstance(item, dict):
            continue
        draft_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        if not draft_id or not title:
            continue
        output.append({
            "id": draft_id,
            "createdAt": str(item.get("createdAt") or ""),
            "title": title,
            "documentType": str(item.get("documentType") or "PS"),
            "targetProgram": str(item.get("targetProgram") or ""),
            "factCount": _safe_int(item.get("factCount")),
            "gapCount": _safe_int(item.get("gapCount")),
            "wordCount": _safe_int(item.get("wordCount")),
        })
    return output


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _unique_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item) for item in value if str(item).strip()))



def profile_store_secret(db_path: Path = DB_PATH) -> bytes:
    return _secret_bytes(db_path)



def _secret_bytes(db_path: Path) -> bytes:
    configured = get_settings().profile_store_secret or os.environ.get("HARBOR_AGENT_PROFILE_STORE_SECRET")
    if configured:
        return hashlib.sha256(configured.encode("utf-8")).digest()
    secret_path = db_path.parent / ".harborpilot_profile_secret"
    if secret_path.exists():
        return base64.urlsafe_b64decode(secret_path.read_text(encoding="utf-8").encode("ascii"))
    secret = secrets.token_bytes(32)
    secret_path.write_text(base64.urlsafe_b64encode(secret).decode("ascii"), encoding="utf-8")
    return secret


def _protect_json(raw: str, db_path: Path) -> str:
    nonce = secrets.token_bytes(16)
    secret = _secret_bytes(db_path)
    plain = raw.encode("utf-8")
    cipher = _xor_with_keystream(plain, secret, nonce)
    tag = hmac.new(secret, nonce + cipher, hashlib.sha256).digest()
    return ":".join(
        [
            PROTECTED_PREFIX.rstrip(":"),
            base64.urlsafe_b64encode(nonce).decode("ascii"),
            base64.urlsafe_b64encode(cipher).decode("ascii"),
            base64.urlsafe_b64encode(tag).decode("ascii"),
        ]
    )


def _unprotect_json(value: str | None, db_path: Path) -> str:
    if value is None:
        return "null"
    if not value.startswith(PROTECTED_PREFIX):
        return value
    parts = value.split(":")
    if len(parts) not in {3, 4}:
        raise ValueError("Invalid protected profile payload")
    _, nonce_b64, cipher_b64, *tag_parts = parts
    nonce = base64.urlsafe_b64decode(nonce_b64.encode("ascii"))
    cipher = base64.urlsafe_b64decode(cipher_b64.encode("ascii"))
    secret = _secret_bytes(db_path)
    if tag_parts:
        supplied_tag = base64.urlsafe_b64decode(tag_parts[0].encode("ascii"))
        expected_tag = hmac.new(secret, nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(supplied_tag, expected_tag):
            raise ValueError("Protected profile payload failed integrity check")
    plain = _xor_with_keystream(cipher, secret, nonce)
    return plain.decode("utf-8")


def _xor_with_keystream(data: bytes, secret: bytes, nonce: bytes) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < len(data):
        block = hashlib.sha256(secret + nonce + counter.to_bytes(8, "big")).digest()
        output.extend(block)
        counter += 1
    return bytes(byte ^ key for byte, key in zip(data, output))
