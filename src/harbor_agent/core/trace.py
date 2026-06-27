from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from time import perf_counter
from typing import Iterator

from harbor_agent.models import AgentStatus, AgentTraceEvent


class TraceRecorder:
    """Append-only in-memory trace recorder for demo and tests."""

    def __init__(self, workflow_id: str):
        self.workflow_id = workflow_id
        self.events: list[AgentTraceEvent] = []

    @contextmanager
    def span(
        self,
        node: str,
        input_summary: str,
        tool_calls: list[str] | None = None,
        model: str = "mock",
    ) -> Iterator[dict[str, str | AgentStatus]]:
        started_at = datetime.now(UTC)
        state: dict[str, str | AgentStatus] = {
            "status": AgentStatus.completed,
            "output_summary": "",
            "needs_human_reason": "",
        }
        start_perf = perf_counter()
        try:
            yield state
        except Exception as exc:
            state["status"] = AgentStatus.failed
            state["output_summary"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            elapsed = perf_counter() - start_perf
            self.events.append(
                AgentTraceEvent(
                    node=node,
                    status=state["status"],  # type: ignore[arg-type]
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    input_summary=input_summary,
                    output_summary=str(state.get("output_summary", "")),
                    tool_calls=tool_calls or [],
                    model=model,
                    cost_usd=round(elapsed * 0.0001, 6),
                    needs_human_reason=str(state.get("needs_human_reason") or "") or None,
                )
            )

