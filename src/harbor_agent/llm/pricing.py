from __future__ import annotations

import json
from pathlib import Path

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
    input_tokens = max(0, usage.prompt_tokens - (usage.cached_tokens or 0))
    cached_tokens = max(0, usage.cached_tokens or 0)
    return round(
        input_tokens * float(prices.get("input_per_1m", 0)) / 1_000_000
        + cached_tokens * float(prices.get("cached_input_per_1m", prices.get("input_per_1m", 0))) / 1_000_000
        + usage.completion_tokens * float(prices.get("output_per_1m", 0)) / 1_000_000,
        8,
    )
