"""Pytest-wide database isolation.

Every default store path is redirected into a per-test temporary directory so
tests and the deterministic eval suite never write into the repository
``data/`` directory (``data/agent_runtime.sqlite``,
``data/harborpilot.sqlite3``, review exports and source snapshots).

Individual tests may still override any path explicitly with their own
``monkeypatch``; pytest restores the values set here after each test.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_repo_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from harbor_agent.services import (
        agent_runtime,
        information_store,
        profile_store,
        program_store,
        review_store,
    )
    from harbor_agent.services import data_loader, source_snapshot

    runtime_db = tmp_path / "agent_runtime.sqlite"
    catalog_db = tmp_path / "harborpilot.sqlite3"

    monkeypatch.setattr(agent_runtime, "DB_PATH", runtime_db)
    monkeypatch.setattr(program_store, "DB_PATH", catalog_db)
    monkeypatch.setattr(profile_store, "DB_PATH", catalog_db)
    monkeypatch.setattr(information_store, "DB_PATH", catalog_db)
    monkeypatch.setattr(data_loader, "PROGRAM_DB_PATH", catalog_db)
    monkeypatch.setattr(review_store, "DB_PATH", catalog_db)
    monkeypatch.setattr(
        review_store,
        "STORE_PATH",
        tmp_path / "reviewed_field_evidence.local.json",
    )
    monkeypatch.setattr(source_snapshot, "SNAPSHOT_DIR", tmp_path / "source_snapshots")
