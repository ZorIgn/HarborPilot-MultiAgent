from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from harbor_agent.models import Program, SourceRegistry
from harbor_agent.services.program_store import DB_PATH as PROGRAM_DB_PATH
from harbor_agent.services.program_store import PROGRAM_JSON, PROGRAM_URL_OVERRIDES, load_programs_from_store

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data"


def load_json(name: str) -> Any:
    with (DATA_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_programs() -> list[Program]:
    return _load_programs_for_signature(_program_store_signature())


@lru_cache(maxsize=8)
def _load_programs_for_signature(_signature: tuple[tuple[str, int, int], ...]) -> list[Program]:
    return load_programs_from_store(db_path=PROGRAM_DB_PATH, seed_json_path=PROGRAM_JSON)


def _program_store_signature() -> tuple[tuple[str, int, int], ...]:
    return tuple(_file_signature(path) for path in (PROGRAM_DB_PATH, PROGRAM_JSON, PROGRAM_URL_OVERRIDES))


def _file_signature(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return (str(path), -1, -1)
    return (str(path), stat.st_mtime_ns, stat.st_size)


load_programs.cache_clear = _load_programs_for_signature.cache_clear  # type: ignore[attr-defined]


@lru_cache(maxsize=1)
def load_taxonomy() -> dict[str, Any]:
    return load_json("taxonomy.json")


@lru_cache(maxsize=1)
def load_form_definition() -> dict[str, Any]:
    return load_json("form_definition.json")


@lru_cache(maxsize=1)
def load_questionnaire_schema() -> dict[str, Any]:
    return load_json("writing_questionnaire_schema.json")


@lru_cache(maxsize=1)
def load_cv_profile_schema() -> dict[str, Any]:
    return load_json("cv_profile_schema.json")


@lru_cache(maxsize=1)
def load_community_sources() -> dict[str, Any]:
    return load_json("community_sources.json")


@lru_cache(maxsize=1)
def load_source_registry() -> SourceRegistry:
    return SourceRegistry.model_validate(load_json("source_registry.json"))

@lru_cache(maxsize=1)
def load_acquisition_sources() -> dict[str, Any]:
    return load_json("acquisition_sources.json")

def clear_data_loader_caches() -> None:
    _load_programs_for_signature.cache_clear()
    load_taxonomy.cache_clear()
    load_form_definition.cache_clear()
    load_questionnaire_schema.cache_clear()
    load_cv_profile_schema.cache_clear()
    load_community_sources.cache_clear()
    load_source_registry.cache_clear()
    load_acquisition_sources.cache_clear()
