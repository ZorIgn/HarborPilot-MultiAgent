from __future__ import annotations

from typing import Type

from pydantic import BaseModel


def openai_tool_schema(name: str, description: str, input_model: Type[BaseModel]) -> dict:
    """Build an OpenAI-compatible function schema from a Pydantic input model."""

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": input_model.model_json_schema(),
        },
    }
