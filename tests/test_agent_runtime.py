from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harbor_agent.services import agent_runtime


def test_agent_job_claim_is_atomic_under_parallel_workers(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(agent_runtime, "DB_PATH", tmp_path / "agent_runtime.sqlite")
    created = agent_runtime.enqueue_agent_job(
        "pytest_parallel_claim",
        "one job should be claimed once",
        payload={"case": "parallel"},
        priority=100,
        max_attempts=3,
    )

    def claim(index: int):
        return agent_runtime.claim_next_agent_job(assigned_to=f"worker_{index}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(8)))

    claimed = [item for item in results if item is not None]
    assert len(claimed) == 1
    assert claimed[0]["job_id"] == created["job_id"]
    assert claimed[0]["status"] == "RUNNING"
    assert claimed[0]["attempts"] == 1
    assert agent_runtime.claim_next_agent_job() is None

    jobs = agent_runtime.list_agent_jobs(limit=10)
    assert jobs[0]["job_id"] == created["job_id"]
    assert jobs[0]["status"] == "RUNNING"
    assert jobs[0]["attempts"] == 1

def test_agent_worker_loop_processes_jobs_until_queue_is_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(agent_runtime, "DB_PATH", tmp_path / "agent_runtime.sqlite")
    from harbor_agent.services import agent_worker

    monkeypatch.setattr(agent_worker, "claim_next_agent_job", agent_runtime.claim_next_agent_job)
    monkeypatch.setattr(agent_worker, "complete_agent_job", agent_runtime.complete_agent_job)

    created = agent_runtime.enqueue_agent_job(
        "unsupported_pytest_workflow",
        "unsupported jobs should be routed to human review",
        payload={"case": "worker-loop"},
        priority=50,
    )

    result = agent_worker.run_agent_worker_loop(max_jobs=5, assigned_to="pytest_worker")

    assert result["processed_count"] == 1
    assert result["empty_polls"] == 1
    assert result["needs_human_count"] == 1
    jobs = agent_runtime.list_agent_jobs(limit=10)
    job = next(item for item in jobs if item["job_id"] == created["job_id"])
    assert job["status"] == "NEEDS_HUMAN"
    assert job["assigned_to"] == "pytest_worker"
    assert "Unsupported workflow" in result["jobs"][0]["result"]["summary"]


def test_agent_worker_cli_entrypoint_exists() -> None:
    assert Path("scripts/run_agent_worker.py").read_text(encoding="utf-8")
    assert "--enqueue-catalog-refresh" in Path("scripts/run_agent_worker.py").read_text(encoding="utf-8")
