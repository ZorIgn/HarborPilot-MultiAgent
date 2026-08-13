from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from harbor_agent.evals.runner import AgentEvalRunner


def _isolate_default_stores(target_dir: Path) -> None:
    """Point every default store at an isolated directory for an eval run.

    Eval runs exercise the real runtime, tools and persistence services, so
    they must not append workflows, checkpoints, traces, evidence candidates or
    source snapshots into the repository ``data/`` directory.
    """

    from harbor_agent.services import (
        agent_runtime,
        information_store,
        profile_store,
        program_store,
        review_store,
    )
    from harbor_agent.services import data_loader, source_snapshot

    target_dir.mkdir(parents=True, exist_ok=True)
    runtime_db = target_dir / "agent_runtime.sqlite"
    catalog_db = target_dir / "harborpilot.sqlite3"

    agent_runtime.DB_PATH = runtime_db
    program_store.DB_PATH = catalog_db
    profile_store.DB_PATH = catalog_db
    information_store.DB_PATH = catalog_db
    data_loader.PROGRAM_DB_PATH = catalog_db
    review_store.DB_PATH = catalog_db
    review_store.STORE_PATH = target_dir / "reviewed_field_evidence.local.json"
    source_snapshot.SNAPSHOT_DIR = target_dir / "source_snapshots"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic HarborPilot Agent Evals.")
    parser.add_argument(
        "--include-trace",
        action="store_true",
        help="Print full per-case runtime traces (disabled by default to keep CI logs readable).",
    )
    parser.add_argument(
        "--db-dir",
        type=Path,
        default=None,
        help="Keep the eval databases in this directory instead of a temporary directory.",
    )
    args = parser.parse_args()

    keep_dir = args.db_dir is not None
    target_dir = args.db_dir or Path(tempfile.mkdtemp(prefix="harborpilot-evals-"))
    _isolate_default_stores(target_dir)
    try:
        report = AgentEvalRunner().run()
        printable = report
        if not args.include_trace:
            printable = {
                **report,
                "results": [
                    {key: value for key, value in item.items() if key != "trace_events"}
                    for item in report["results"]
                ],
            }
        print(json.dumps(printable, ensure_ascii=False, indent=2))
        return 0 if all(item["passed"] for item in report["results"]) else 1
    finally:
        if not keep_dir:
            shutil.rmtree(target_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
