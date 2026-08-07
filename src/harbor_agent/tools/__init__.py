"""Typed deterministic tools used by specialized HarborPilot agents."""

from __future__ import annotations

from harbor_agent.tools.registry import ToolRegistry


def build_default_tool_registry() -> ToolRegistry:
    """Create the single registry shared by all runtime agents."""

    from harbor_agent.tools import (
        assessment_tools,
        catalog_tools,
        evidence_tools,
        extraction_tools,
        matching_tools,
        planning_tools,
        profile_tools,
        review_tools,
        source_tools,
        trust_tools,
        writing_tools,
    )

    definitions = []
    for module in (
        profile_tools,
        evidence_tools,
        assessment_tools,
        catalog_tools,
        matching_tools,
        source_tools,
        extraction_tools,
        trust_tools,
        planning_tools,
        writing_tools,
        review_tools,
    ):
        definitions.extend(module.definitions())
    return ToolRegistry(definitions)


__all__ = ["ToolRegistry", "build_default_tool_registry"]
