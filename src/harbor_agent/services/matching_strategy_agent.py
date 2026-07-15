from __future__ import annotations

from copy import deepcopy
from typing import Any

from harbor_agent.core.llm import LLMProvider
from harbor_agent.services.matching_strategy import load_matching_strategy, save_matching_strategy

ALLOWED_TOP_LEVEL_FIELDS = {
    "institution_tiers",
    "recommendation_quotas",
    "application_mix_quotas",
    "profile_tier_base",
}


def propose_matching_strategy(
    *,
    instruction: str,
    llm: LLMProvider,
    apply: bool = False,
) -> dict[str, Any]:
    current = load_matching_strategy()
    proposal = _fallback_patch(current, instruction)
    model_used = "deterministic_fallback"
    if llm.name != "mock":
        try:
            completion = llm.complete_json(
                system=(
                    "You are a cautious admissions strategy agent. Propose only configuration changes for "
                    "Hong Kong/Singapore taught-master programme matching. Do not invent schools, official facts, "
                    "deadlines, admission probabilities, or programme requirements. Return JSON only."
                ),
                user=(
                    f"Current strategy JSON: {current}\n\n"
                    f"Consultant instruction: {instruction}\n\n"
                    "Return a conservative patch. Only these top-level keys may be changed: "
                    f"{sorted(ALLOWED_TOP_LEVEL_FIELDS)}. Keep all numeric quota values as integers."
                ),
                schema_hint={
                    "patch": {
                        "recommendation_quotas": {"reach": 0, "target": 0, "safe": 0, "candidate": 0, "not_recommended": 0, "max_total": 0},
                        "application_mix_quotas": {"reach": 0, "target": 0, "safe": 0, "max_total": 0},
                        "profile_tier_base": {"regular": 0.0},
                    },
                    "rationale": ["string"],
                    "risk_controls": ["string"],
                },
            )
            proposal = _sanitize_patch(completion.get("patch") or {}, current) or proposal
            model_used = llm.name
        except Exception as exc:
            proposal["_model_error"] = f"{type(exc).__name__}: {exc}"
    patched = _merge_strategy(current, proposal)
    saved = save_matching_strategy(patched) if apply else None
    return {
        "model": model_used,
        "applied": apply,
        "instruction": instruction,
        "patch": proposal,
        "strategy": saved or patched,
        "rationale": _rationale(instruction, proposal),
        "risk_controls": [
            "Hard eligibility rules still run after strategy tuning.",
            "LLM proposals cannot change programme facts, official-source gates, or deadline trust rules.",
            "Admin should run scenario audit before using a new strategy with students.",
        ],
    }


def _fallback_patch(current: dict[str, Any], instruction: str) -> dict[str, Any]:
    text = instruction.lower()
    patch: dict[str, Any] = {}
    quotas = dict(current.get("recommendation_quotas", {}))
    mix = dict(current.get("application_mix_quotas", {}))
    tier_base = dict(current.get("profile_tier_base", {}))
    if any(term in text for term in ["safe", "\u4fdd\u5e95", "conservative", "\u4fdd\u5b88"]):
        quotas["safe"] = min(18, int(quotas.get("safe", 12)) + 3)
        quotas["reach"] = max(8, int(quotas.get("reach", 14)) - 2)
        mix["safe"] = min(5, int(mix.get("safe", 3)) + 1)
        mix["reach"] = max(2, int(mix.get("reach", 4)) - 1)
        tier_base["regular"] = round(float(tier_base.get("regular", 3.15)) - 0.08, 2)
        patch.update({"recommendation_quotas": quotas, "application_mix_quotas": mix, "profile_tier_base": tier_base})
    elif any(term in text for term in ["reach", "\u51b2\u523a", "aggressive", "\u6fc0\u8fdb"]):
        quotas["reach"] = min(18, int(quotas.get("reach", 14)) + 2)
        quotas["safe"] = max(8, int(quotas.get("safe", 12)) - 2)
        mix["reach"] = min(5, int(mix.get("reach", 4)) + 1)
        patch.update({"recommendation_quotas": quotas, "application_mix_quotas": mix})
    else:
        quotas["candidate"] = min(16, int(quotas.get("candidate", 10)) + 2)
        patch["recommendation_quotas"] = quotas
    return _sanitize_patch(patch, current) or {}


def _sanitize_patch(patch: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in patch.items():
        if key not in ALLOWED_TOP_LEVEL_FIELDS or not isinstance(value, dict):
            continue
        baseline = current.get(key, {})
        if not isinstance(baseline, dict):
            continue
        clean[key] = _sanitize_nested(value, baseline)
    return clean


def _sanitize_nested(value: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    output = deepcopy(baseline)
    for key, proposed in value.items():
        if key not in baseline:
            continue
        if isinstance(baseline[key], dict) and isinstance(proposed, dict):
            output[key] = _sanitize_nested(proposed, baseline[key])
        elif isinstance(baseline[key], int):
            output[key] = max(0, min(200, int(proposed)))
        elif isinstance(baseline[key], float):
            output[key] = max(0.0, min(6.0, round(float(proposed), 2)))
        elif isinstance(baseline[key], list) and isinstance(proposed, list):
            output[key] = [str(item) for item in proposed[:80]]
        elif isinstance(baseline[key], str):
            output[key] = str(proposed)[:160]
    return output


def _merge_strategy(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(current)
    for key, value in patch.items():
        if key.startswith("_"):
            continue
        if key in ALLOWED_TOP_LEVEL_FIELDS:
            merged[key] = value
    merged["version"] = current.get("version", "v1-configurable-agent-strategy")
    merged["agent_adjustable_fields"] = sorted(ALLOWED_TOP_LEVEL_FIELDS)
    return merged


def _rationale(instruction: str, patch: dict[str, Any]) -> list[str]:
    changed = [key for key in patch if not key.startswith("_")]
    return [
        f"Consultant instruction parsed: {instruction or 'no instruction supplied'}.",
        f"Changed configurable fields: {', '.join(changed) if changed else 'none'}.",
        "The proposal tunes sorting and quota behavior only; eligibility and source trust remain guarded elsewhere.",
    ]
