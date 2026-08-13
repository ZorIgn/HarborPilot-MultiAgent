from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from harbor_agent.runtime.checkpoint import (
    CheckpointPolicy,
    CheckpointPolicyConfig,
    save_checkpoint,
)
from harbor_agent.runtime.state import AgentState, WorkflowGoal, WorkflowStatus
from harbor_agent.services import agent_runtime
from harbor_agent.services.agent_runtime import create_multi_agent_workflow, save_workflow_checkpoint


def _state(workflow_id: str, *, step_count: int = 0, status: WorkflowStatus = WorkflowStatus.RUNNING) -> AgentState:
    return AgentState(
        workflow_id=workflow_id,
        goal=WorkflowGoal.BACKGROUND_ASSESSMENT,
        status=status,
        step_count=step_count,
    )


def test_checkpoint_policy_uses_long_interval_and_step_threshold() -> None:
    policy = CheckpointPolicy(
        CheckpointPolicyConfig(
            min_interval=timedelta(hours=2),
            min_step_interval=100,
        )
    )
    first = _state("policy-test", step_count=0)

    assert policy.should_save(first)
    policy.record_saved(first)
    assert not policy.should_save(_state("policy-test", step_count=99))
    assert policy.should_save(_state("policy-test", step_count=100))

    policy.record_saved(_state("policy-test", step_count=100))
    policy._last_saved_at["policy-test"] = datetime.now(UTC) - timedelta(hours=3)
    assert policy.should_save(_state("policy-test", step_count=101))


def test_save_checkpoint_skips_ordinary_running_state_until_policy_allows_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(agent_runtime, "DB_PATH", tmp_path / "agent_runtime.sqlite")
    workflow_id = f"policy_db_{uuid4().hex}"
    initial = _state(workflow_id)
    create_multi_agent_workflow(workflow_id, initial.goal.value, initial.model_dump(mode="json"))
    policy = CheckpointPolicy(
        CheckpointPolicyConfig(
            min_interval=timedelta(hours=2),
            min_step_interval=100,
        )
    )

    assert save_checkpoint(initial, force=True, policy=policy)
    assert save_checkpoint(_state(workflow_id, step_count=1), policy=policy) is None
    assert save_checkpoint(_state(workflow_id, step_count=100), policy=policy)

    with agent_runtime._connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM agent_checkpoints WHERE workflow_id = ?",
            (workflow_id,),
        ).fetchone()[0]
    assert count == 2


def test_checkpoint_retention_keeps_two_snapshots_per_historical_day(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(agent_runtime, "DB_PATH", tmp_path / "agent_runtime.sqlite")
    monkeypatch.setattr(agent_runtime, "CHECKPOINT_MAX_PER_WORKFLOW", 6)
    monkeypatch.setattr(agent_runtime, "CHECKPOINT_DAILY_KEEP", 2)
    monkeypatch.setattr(agent_runtime, "CHECKPOINT_MAX_TOTAL", 50)
    workflow_id = f"retention_day_{uuid4().hex}"
    state = _state(workflow_id)
    create_multi_agent_workflow(workflow_id, state.goal.value, state.model_dump(mode="json"))
    timestamps = iter(
        [
            "2026-08-10T01:00:00+00:00",
            "2026-08-10T02:00:00+00:00",
            "2026-08-10T03:00:00+00:00",
            "2026-08-11T01:00:00+00:00",
            "2026-08-12T01:00:00+00:00",
        ]
    )
    monkeypatch.setattr(agent_runtime, "_now", lambda: next(timestamps))

    for step in range(5):
        save_workflow_checkpoint(
            workflow_id=workflow_id,
            state_schema_version=state.schema_version,
            state_json=_state(workflow_id, step_count=step).model_dump(mode="json"),
            status=WorkflowStatus.RUNNING.value,
            current_agent="AssessmentAgent",
        )

    with agent_runtime._connect() as conn:
        rows = conn.execute(
            """
            SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count
            FROM agent_checkpoints
            WHERE workflow_id = ?
            GROUP BY day
            ORDER BY day
            """,
            (workflow_id,),
        ).fetchall()
    assert [(row["day"], row["count"]) for row in rows] == [
        ("2026-08-10", 2),
        ("2026-08-11", 1),
        ("2026-08-12", 1),
    ]


def test_checkpoint_retention_enforces_global_cap(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(agent_runtime, "DB_PATH", tmp_path / "agent_runtime.sqlite")
    monkeypatch.setattr(agent_runtime, "CHECKPOINT_MAX_PER_WORKFLOW", 12)
    monkeypatch.setattr(agent_runtime, "CHECKPOINT_DAILY_KEEP", 2)
    monkeypatch.setattr(agent_runtime, "CHECKPOINT_MAX_TOTAL", 3)
    monkeypatch.setattr(agent_runtime, "_now", lambda: "2026-08-13T01:00:00+00:00")

    for index in range(5):
        workflow_id = f"retention_global_{index}_{uuid4().hex}"
        state = _state(workflow_id, status=WorkflowStatus.COMPLETED)
        create_multi_agent_workflow(workflow_id, state.goal.value, state.model_dump(mode="json"))
        save_workflow_checkpoint(
            workflow_id=workflow_id,
            state_schema_version=state.schema_version,
            state_json=state.model_dump(mode="json"),
            status=WorkflowStatus.COMPLETED.value,
            current_agent="SupervisorAgent",
        )

    with agent_runtime._connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM agent_checkpoints").fetchone()[0]
    assert count <= 3
