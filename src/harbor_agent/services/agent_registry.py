"""Compatibility entry point for the real supervisor-runtime registry.

The application used to expose a static catalogue of Python classes as an
"agent registry". Runtime ownership now lives in ``runtime_agent_registry``:
it builds the concrete Supervisor and specialized agents, verifies their tool
permissions, and reports their actual contracts.

Keep this module as a stable import path for callers that predate the runtime
move. It deliberately does not define a second registry or workflow order.
"""

from harbor_agent.services.runtime_agent_registry import build_agent_system_report

__all__ = ["build_agent_system_report"]
