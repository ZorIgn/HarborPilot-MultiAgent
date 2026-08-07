from __future__ import annotations

from pydantic import BaseModel, Field

from harbor_agent.policies.source_policy import UNTRUSTED_SOURCE_PREAMBLE
from harbor_agent.runtime.state import AgentState
from harbor_agent.services.source_snapshot import extract_field_candidates
from harbor_agent.tools.base import ToolDefinition


class ExtractFieldsInput(BaseModel):
    program_id: str
    source_url: str
    source_text: str = Field(max_length=200_000)


class ExtractedFieldsResult(BaseModel):
    program_id: str
    source_url: str
    extraction_policy: str
    fields: list[dict] = Field(default_factory=list)


def _extract(_: AgentState, args: ExtractFieldsInput) -> ExtractedFieldsResult:
    # External content stays data; it is never inserted into a system prompt.
    candidates = extract_field_candidates(args.source_text)
    return ExtractedFieldsResult(
        program_id=args.program_id,
        source_url=args.source_url,
        extraction_policy=UNTRUSTED_SOURCE_PREAMBLE,
        fields=[item.model_dump(mode="json") for item in candidates if item is not None],
    )


def definitions() -> list[ToolDefinition]:
    return [ToolDefinition("extract_program_fields", "Extract typed field candidates from untrusted official-source text.", ExtractFieldsInput, ExtractedFieldsResult, _extract)]
