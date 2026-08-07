from __future__ import annotations

import json
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from harbor_agent.runtime.errors import LLMStructuredOutputError

T = TypeVar("T", bound=BaseModel)


def parse_structured_output(content: str, model: Type[T]) -> T:
    """Parse and validate a provider JSON response without permissive fallback."""

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMStructuredOutputError("model response was not JSON") from exc
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise LLMStructuredOutputError("model response did not match the required schema") from exc
