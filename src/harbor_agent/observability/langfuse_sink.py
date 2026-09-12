"""Optional, best-effort export of runtime observations to Langfuse."""
# ruff: noqa: BLE001

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

from harbor_agent.config import get_settings
from harbor_agent.observability.logging import diagnostic
from harbor_agent.observability.privacy import safe_content, safe_metadata, safe_text


def mask_otel_spans(*, params: Any) -> Any:
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    patches = {}
    for identifier, span in params.spans.items():
        updates = {}
        for key, value in span.attributes.items():
            if not isinstance(value, str):
                continue
            if key in {"langfuse.observation.input", "langfuse.observation.output"}:
                try:
                    updates[key] = json.dumps(safe_content(json.loads(value)), ensure_ascii=False)
                except (ValueError, TypeError):
                    updates[key] = "[redacted]"
            elif "metadata" in key or key == "langfuse.observation.status_message":
                updates[key] = safe_text(value) or ""
        if updates:
            patches[identifier] = OtelSpanPatch(set_attributes=updates)
    return MaskOtelSpansResult(span_patches=patches)


class LangfuseSink:
    def __init__(self, client: Any, *, sample_rate: float = 1.0) -> None:
        self.client = client
        self.sample_rate = sample_rate

    def accepts(self, trace_id: str) -> bool:
        # A single decision applies to all spans and scores in an execution.
        return int(trace_id[:16], 16) / 2**64 < self.sample_rate

    def start(
        self,
        *,
        trace_id: str,
        workflow_id: str,
        parent: Any,
        name: str,
        kind: str,
        metadata: dict[str, Any],
        input: Any = None,
        model: str | None = None,
    ) -> Any:
        try:
            from langfuse import propagate_attributes

            with propagate_attributes(
                session_id=workflow_id, trace_name=name if parent is None else None
            ):
                creator = (
                    parent.start_observation
                    if parent is not None
                    else self.client.start_observation
                )
                kwargs = {} if parent is not None else {"trace_context": {"trace_id": trace_id}}
                return creator(
                    name=name,
                    as_type=kind,
                    input=safe_content(input),
                    metadata=safe_metadata(metadata),
                    model=model,
                    **kwargs,
                )
        except Exception as exc:
            diagnostic("langfuse.start_failed", error=exc, workflow_id=workflow_id)
            return None

    def finish(
        self, handle: Any, *, output: Any, metadata: dict[str, Any], usage: Any, cost: float | None
    ) -> None:
        if handle is None:
            return
        try:
            kwargs: dict[str, Any] = {
                "output": safe_content(output),
                "metadata": safe_metadata(metadata),
                "level": (
                    "ERROR"
                    if metadata.get("outcome") == "error"
                    else "WARNING"
                    if metadata.get("policy_result") == "rejected"
                    else "DEFAULT"
                ),
                "status_message": metadata.get("error_type"),
            }
            if usage is not None:
                details = {}
                if usage.prompt_tokens is not None:
                    cached = usage.cached_tokens
                    if cached is not None and 0 <= cached <= usage.prompt_tokens:
                        details["input"] = usage.prompt_tokens - cached
                        details["input_cached_tokens"] = cached
                    else:
                        details["input"] = usage.prompt_tokens
                if usage.completion_tokens is not None:
                    details["output"] = usage.completion_tokens
                kwargs["usage_details"] = details
                if cost is not None:
                    kwargs["cost_details"] = {"total": cost}
            handle.update(**kwargs)
        except Exception as exc:
            diagnostic("langfuse.update_failed", error=exc)
        finally:
            try:
                handle.end()
            except Exception as exc:
                diagnostic("langfuse.end_failed", error=exc)

    def event(
        self, *, parent: Any, trace_id: str, workflow_id: str, name: str, metadata: dict[str, Any]
    ) -> None:
        try:
            if name == "policy_check":
                handle = self.start(
                    trace_id=trace_id,
                    workflow_id=workflow_id,
                    parent=parent,
                    name="policy.check",
                    kind="guardrail",
                    metadata=metadata,
                )
                self.finish(
                    handle, output=safe_metadata(metadata), metadata=metadata, usage=None, cost=None
                )
                return
            from langfuse import propagate_attributes

            with propagate_attributes(session_id=workflow_id):
                creator = parent.create_event if parent is not None else self.client.create_event
                kwargs = {} if parent is not None else {"trace_context": {"trace_id": trace_id}}
                creator(name=name, metadata=safe_metadata(metadata), **kwargs)
        except Exception as exc:
            diagnostic("langfuse.event_failed", error=exc, workflow_id=workflow_id)

    def score(self, *, trace_id: str, case_id: str, passed: bool) -> None:
        if not self.accepts(trace_id):
            return
        try:
            self.client.create_score(
                trace_id=trace_id,
                name="case_passed",
                value=float(passed),
                data_type="BOOLEAN",
                score_id=f"{trace_id}-case-passed",
                metadata=safe_metadata({"case_id": case_id}),
            )
        except Exception as exc:
            diagnostic("langfuse.score_failed", error=exc, case_id=case_id)

    def shutdown(self) -> None:
        try:
            self.client.shutdown()
        except Exception as exc:
            diagnostic("langfuse.shutdown_failed", error=exc)


@lru_cache(maxsize=1)
def get_langfuse_sink() -> LangfuseSink | None:
    settings = get_settings()
    if not settings.langfuse_enabled:
        return None
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        diagnostic("langfuse.credentials_missing")
        return None
    try:
        from langfuse import Langfuse
        from opentelemetry.sdk.trace import TracerProvider

        url = urlsplit(settings.langfuse_base_url)
        if url.username or url.password or url.query or url.fragment or not url.hostname:
            raise ValueError("invalid Langfuse base URL")
        if url.scheme not in {"http", "https"}:
            raise ValueError("Langfuse requires an HTTP(S) base URL")
        client = Langfuse(
            public_key=settings.langfuse_public_key.get_secret_value(),
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            base_url=settings.langfuse_base_url,
            environment=settings.langfuse_environment,
            release=settings.langfuse_release,
            timeout=3,
            flush_at=64,
            flush_interval=2,
            sample_rate=1.0,
            tracer_provider=TracerProvider(),
            mask_otel_spans=mask_otel_spans,
            should_export_span=lambda span: span.instrumentation_scope.name == "langfuse-sdk",
        )
        return LangfuseSink(client, sample_rate=settings.langfuse_sample_rate)
    except Exception as exc:
        diagnostic("langfuse.initialization_failed", error=exc)
        return None


def shutdown_observability() -> None:
    if get_langfuse_sink.cache_info().currsize:
        sink = get_langfuse_sink()
        if sink is not None:
            sink.shutdown()
    get_langfuse_sink.cache_clear()
