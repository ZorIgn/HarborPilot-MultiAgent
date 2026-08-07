from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from harbor_agent.services.data_loader import DATA_DIR


STRATEGY_PATH = DATA_DIR / "matching_strategy.json"


DEFAULT_STRATEGY: dict[str, Any] = {
    "version": "v1-configurable-agent-strategy",
    "institution_tiers": {
        "elite": {
            "score": 5.1,
            "aliases": [
                "the university of hong kong",
                "hong kong university of science and technology",
                "the chinese university of hong kong",
                "national university of singapore",
                "nanyang technological university",
            ],
        },
        "strong": {
            "score": 4.15,
            "aliases": [
                "city university of hong kong",
                "the hong kong polytechnic university",
                "singapore management university",
                "singapore university of technology and design",
            ],
        },
        "solid": {
            "score": 3.15,
            "aliases": [
                "hong kong baptist university",
                "lingnan university",
                "the education university of hong kong",
            ],
        },
    },
    "profile_tier_base": {
        "C9": 4.75,
        "985": 4.45,
        "211": 4.05,
        "double_first_class": 3.85,
        "overseas": 4.1,
        "regular": 3.15,
        "unknown": 3.25,
    },
    "recommendation_quotas": {
        "reach": 14,
        "target": 14,
        "safer": 12,
        "candidate": 10,
        "not_recommended": 12,
        "max_total": 60,
    },
    "application_mix_quotas": {
        "reach": 4,
        "target": 4,
        "safer": 3,
        "max_total": 10,
    },
    "agent_adjustable_fields": [
        "institution_tiers",
        "recommendation_quotas",
        "application_mix_quotas",
        "profile_tier_base",
    ],
}


@lru_cache(maxsize=1)
def load_matching_strategy() -> dict[str, Any]:
    if not STRATEGY_PATH.exists():
        save_matching_strategy(DEFAULT_STRATEGY)
        return DEFAULT_STRATEGY
    with STRATEGY_PATH.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    return _normalize_strategy_bands(_deep_merge(DEFAULT_STRATEGY, _normalize_strategy_bands(loaded)))


def save_matching_strategy(strategy: dict[str, Any]) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged = _normalize_strategy_bands(_deep_merge(DEFAULT_STRATEGY, _normalize_strategy_bands(strategy)))
    STRATEGY_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    load_matching_strategy.cache_clear()
    return merged


def strategy_source() -> dict[str, Any]:
    strategy = load_matching_strategy()
    return {
        "path": str(STRATEGY_PATH),
        "version": strategy.get("version"),
        "agent_adjustable_fields": strategy.get("agent_adjustable_fields", []),
    }


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    output = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(output.get(key), dict):
            output[key] = _deep_merge(output[key], value)
        else:
            output[key] = value
    return output


def _normalize_strategy_bands(strategy: dict[str, Any]) -> dict[str, Any]:
    """Accept the retired ``safe`` input key without emitting it again."""
    normalized = dict(strategy)
    for field in ("recommendation_quotas", "application_mix_quotas"):
        source = normalized.get(field)
        if not isinstance(source, dict):
            continue
        quotas = dict(source)
        legacy_safe = quotas.pop("safe", None)
        if "safer" not in quotas and legacy_safe is not None:
            quotas["safer"] = legacy_safe
        normalized[field] = quotas
    return normalized
