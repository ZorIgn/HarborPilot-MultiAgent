"""Structured runtime diagnostics correlated with persisted trace events."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from harbor_agent.observability.privacy import safe_metadata


class RuntimeLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
                "level": record.levelname,
                "event": record.msg,
                **safe_metadata(getattr(record, "context", {})),
            },
            ensure_ascii=False,
        )


def configure_logging() -> None:
    logger = logging.getLogger("harbor_agent")
    if not any(isinstance(handler.formatter, RuntimeLogFormatter) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(RuntimeLogFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def diagnostic(event: str, *, error: BaseException | None = None, **context: object) -> None:
    # Exception bodies can contain provider responses or connection credentials.
    if error is not None:
        context["error_type"] = type(error).__name__
    logging.getLogger("harbor_agent.runtime").warning(event, extra={"context": context})
