from __future__ import annotations

from collections.abc import Callable
from time import sleep
from typing import TypeVar

T = TypeVar("T")


def with_retry(operation: Callable[[], T], *, attempts: int = 3, retryable: tuple[type[Exception], ...] = (TimeoutError,)) -> T:
    """Retry a bounded number of transient operations with a tiny backoff."""

    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return operation()
        except retryable as exc:
            last_error = exc
            if attempt + 1 < max(1, attempts):
                sleep(0.1 * (2**attempt))
    assert last_error is not None
    raise last_error
