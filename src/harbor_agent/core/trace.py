from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from time import perf_counter
from typing import Iterator

from harbor_agent.models import AgentStatus, AgentTraceEvent
from harbor_agent.services.agent_runtime import complete_agent_run, record_agent_step, start_agent_run


class TraceRecorder:
    """Append-only trace recorder plus persisted local agent-runtime events."""

    def __init__(self, workflow_id: str, workflow_name: str | None = None):
        self.workflow_id = workflow_id
        self.workflow_name = workflow_name or "unknown"
        self.events: list[AgentTraceEvent] = []
        start_agent_run(workflow_id, self.workflow_name)

    def complete(self, status: str = "COMPLETED") -> None:
        complete_agent_run(self.workflow_id, status)

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
            finished_at = datetime.now(UTC)
            elapsed = perf_counter() - start_perf
            event = AgentTraceEvent(
                node=node,
                status=state["status"],  # type: ignore[arg-type]
                started_at=started_at,
                finished_at=finished_at,
                input_summary=input_summary,
                output_summary=str(state.get("output_summary", "")),
                tool_calls=tool_calls or [],
                model=model,
                cost_usd=None,
                needs_human_reason=str(state.get("needs_human_reason") or "") or None,
            )
            self.events.append(event)
            record_agent_step(
                workflow_id=self.workflow_id,
                node=node,
                status=event.status,
                input_summary=event.input_summary,
                output_summary=event.output_summary,
                tool_calls=event.tool_calls,
                model=event.model,
                started_at=event.started_at,
                finished_at=event.finished_at,
                needs_human_reason=event.needs_human_reason,
            )

