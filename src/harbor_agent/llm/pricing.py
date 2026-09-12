from __future__ import annotations

import json
from math import isfinite
from pathlib import Path
from typing import Any

from harbor_agent.llm.response import LLMUsage

_PRICING_PATH = Path(__file__).resolve().parents[3] / "data" / "model_pricing.json"


def load_model_pricing() -> dict[str, dict[str, float]]:
    """Load explicit prices. An unknown model deliberately has no price."""

    try:
        raw = json.loads(_PRICING_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(key): dict(value) for key, value in raw.items() if isinstance(value, dict)}


def calculate_cost_usd(provider: str | None, model: str | None, usage: LLMUsage) -> float | None:
    """Calculate cost only from provider-reported tokens and configured prices."""

    if not provider or not model or usage.prompt_tokens is None or usage.completion_tokens is None:
        return None
    prices = load_model_pricing().get(f"{provider}/{model}") or load_model_pricing().get(model)
    if prices is None:
        return None

    input_price = _price(prices.get("input_per_1m"))
    output_price = _price(prices.get("output_per_1m"))
    if input_price is None or output_price is None:
        return None

    cached_tokens = usage.cached_tokens or 0
    if cached_tokens < 0 or cached_tokens > usage.prompt_tokens:
        return None
    cached_price = 0.0
    if cached_tokens:
        cached_price = _price(prices.get("cached_input_per_1m"))
        if cached_price is None:
            return None
    input_tokens = usage.prompt_tokens - cached_tokens
    return round(
        input_tokens * input_price / 1_000_000
        + cached_tokens * cached_price / 1_000_000
        + usage.completion_tokens * output_price / 1_000_000,
        8,
    )


def _price(value: Any) -> float | None:
    """Return a configured non-negative finite price, preserving missing data."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    price = float(value)
    return price if isfinite(price) and price >= 0 else None
