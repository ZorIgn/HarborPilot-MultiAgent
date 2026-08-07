from __future__ import annotations

from harbor_agent.runtime.state import AgentState
from harbor_agent.services.agent_runtime import load_workflow_checkpoint, save_workflow_checkpoint


def save_checkpoint(state: AgentState) -> str:
    """Persist a typed state after every agent turn or interrupt."""

    return save_workflow_checkpoint(
        workflow_id=state.workflow_id,
        state_schema_version=state.schema_version,
        state_json=state.model_dump(mode="json"),
        status=state.status.value,
        current_agent=state.current_agent,
    )


def load_checkpoint(workflow_id: str) -> AgentState | None:
    """Load the latest valid checkpoint, if the workflow has one."""

    record = load_workflow_checkpoint(workflow_id)
    if record is None:
        return None
    return AgentState.model_validate(record["state"])
