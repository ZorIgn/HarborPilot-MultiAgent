"""Explicit errors used by the multi-agent runtime.

Keeping these errors separate lets the API distinguish a bad model response,
an invalid tool request, and a workflow that needs a human decision.
"""


class AgentRuntimeError(RuntimeError):
    """Base error for a runtime operation that cannot continue."""


class AgentDecisionValidationError(AgentRuntimeError):
    """An agent returned a decision that does not satisfy its contract."""


class ToolNotFoundError(AgentRuntimeError):
    """The requested tool is not registered."""


class ToolPermissionError(AgentRuntimeError):
    """An agent attempted to use a tool outside its allowlist."""


class ToolArgumentValidationError(AgentRuntimeError):
    """Tool arguments failed Pydantic validation."""


class ToolExecutionError(AgentRuntimeError):
    """A registered tool raised while doing its deterministic work."""


class LLMTimeoutError(AgentRuntimeError):
    """The configured model provider timed out."""


class LLMStructuredOutputError(AgentRuntimeError):
    """The configured model did not return the requested typed response."""


class WorkflowLimitExceeded(AgentRuntimeError):
    """The workflow exceeded one of its explicit execution limits."""


class HumanReviewRequired(AgentRuntimeError):
    """A policy requires a human decision before the workflow can proceed."""


class UnsafeSourceError(AgentRuntimeError):
    """A source URL failed the network/source safety policy."""
