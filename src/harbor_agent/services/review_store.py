from __future__ import annotations

import json
from pathlib import Path

from harbor_agent.models import FieldEvidenceRecord
from harbor_agent.services.data_loader import DATA_DIR

STORE_PATH = DATA_DIR / "reviewed_field_evidence.local.json"


def load_published_field_records() -> list[FieldEvidenceRecord]:
    if not STORE_PATH.exists():
        return []
    try:
        raw = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    records: list[FieldEvidenceRecord] = []
    for item in raw:
        try:
            records.append(FieldEvidenceRecord.model_validate(item))
        except Exception:
            continue
    return records


def save_published_field_record(record: FieldEvidenceRecord) -> None:
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
    STORE_PATH.write_text(
        json.dumps([item.model_dump(mode="json") for item in remaining], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )