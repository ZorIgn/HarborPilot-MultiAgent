from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from harbor_agent.runtime.state import AgentState
from harbor_agent.services.agent_runtime import load_workflow_checkpoint, save_workflow_checkpoint


@dataclass(frozen=True)
class CheckpointPolicyConfig:
    """Long-interval checkpoint defaults for the in-process runtime.

    A normal running workflow is deliberately not checkpointed on every agent
    turn.  The workflow still checkpoints immediately at explicit recovery
    boundaries (start, resume, wait, failure and completion).  The generous
    interval values below are intentional: the default workflow has a bounded
    number of turns, so most runs keep only their start and terminal snapshots.
    """

    min_interval: timedelta = timedelta(hours=4)
    min_step_interval: int = 100


@dataclass
class CheckpointPolicy:
    """Throttle ordinary checkpoints while preserving explicit recovery points."""

    config: CheckpointPolicyConfig = field(default_factory=CheckpointPolicyConfig)
    _last_saved_at: dict[str, datetime] = field(default_factory=dict, init=False, repr=False)
    _last_saved_step: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def should_save(self, state: AgentState, *, force: bool = False) -> bool:
        """Return whether this state should create another full snapshot.

        Non-running states are always persisted because they are recovery
        boundaries.  For a running workflow, either a long wall-clock gap or a
        large number of state transitions is enough to create a checkpoint.
        """

        if force or state.status.value != "RUNNING":
            return True

        last_at = self._last_saved_at.get(state.workflow_id)
        last_step = self._last_saved_step.get(state.workflow_id)
        if last_at is None or last_step is None:
            return True

        now = datetime.now(UTC)
        return (
            now - last_at >= self.config.min_interval
            or state.step_count - last_step >= self.config.min_step_interval
        )

    def record_saved(self, state: AgentState) -> None:
        self._last_saved_at[state.workflow_id] = datetime.now(UTC)
        self._last_saved_step[state.workflow_id] = state.step_count


_DEFAULT_CHECKPOINT_POLICY = CheckpointPolicy()


def save_checkpoint(
    state: AgentState,
    *,
    force: bool = False,
    policy: CheckpointPolicy | None = None,
) -> str | None:
    """Persist a typed state only when policy permits another full snapshot.

    ``force=True`` is reserved for explicit recovery boundaries.  Returning
    ``None`` means the state remained in memory and no database row was added.
    """

    active_policy = policy or _DEFAULT_CHECKPOINT_POLICY
    if not active_policy.should_save(state, force=force):
        return None

    checkpoint_id = save_workflow_checkpoint(
        workflow_id=state.workflow_id,
        state_schema_version=state.schema_version,
        state_json=state.model_dump(mode="json"),
        status=state.status.value,
        current_agent=state.current_agent,
    )
    active_policy.record_saved(state)
    return checkpoint_id


def load_checkpoint(workflow_id: str) -> AgentState | None:
    """Load the latest valid checkpoint, if the workflow has one."""

    record = load_workflow_checkpoint(workflow_id)
    if record is None:
        return None
    return AgentState.model_validate(record["state"])
