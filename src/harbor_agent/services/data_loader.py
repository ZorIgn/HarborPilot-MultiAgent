from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from harbor_agent.models import Program, SourceRegistry

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data"


def load_json(name: str) -> Any:
    with (DATA_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_programs() -> list[Program]:
    return [Program.model_validate(item) for item in load_json("programs_2027_fall.json")]


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
