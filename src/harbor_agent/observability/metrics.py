from __future__ import annotations

from statistics import median
from typing import Iterable


def latency_summary(milliseconds: Iterable[int | None]) -> dict[str, float | int | None]:
    """Compute a compact latency summary for real runtime events."""

    values = sorted(value for value in milliseconds if value is not None)
    if not values:
        return {"count": 0, "p50_ms": None, "p95_ms": None}
    index = min(len(values) - 1, round((len(values) - 1) * 0.95))
    return {"count": len(values), "p50_ms": median(values), "p95_ms": values[index]}
