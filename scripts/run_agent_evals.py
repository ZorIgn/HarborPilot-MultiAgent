from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from harbor_agent.evals.model_replay import PolicyEnvelopeReplayProvider
from harbor_agent.evals.runner import AgentEvalRunner
from harbor_agent.llm.provider import OpenAICompatibleToolCallingProvider
from harbor_agent.observability.langfuse_sink import get_langfuse_sink, shutdown_observability
from harbor_agent.observability.logging import configure_logging


def _isolate_default_stores(target_dir: Path) -> None:
    """Point every default store at an isolated directory for an eval run.

    Eval runs exercise the real runtime, tools and persistence services, so
    they must not append workflows, checkpoints, traces, evidence candidates or
    source snapshots into the repository ``data/`` directory.
    """

    from harbor_agent.services import (
        agent_runtime,
        data_loader,
        information_store,
        profile_store,
        program_store,
        review_store,
        source_snapshot,
    )

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
    provider_group = parser.add_mutually_exclusive_group()
    provider_group.add_argument(
        "--model-replay",
        action="store_true",
        help=(
            "Exercise complete model-driven Supervisor/Specialist paths with a "
            "reproducible policy-envelope provider; this measures runtime integration, "
            "not external model quality."
        ),
    )
    provider_group.add_argument(
        "--live-model",
        action="store_true",
        help=(
            "Run selected workflow cases through the configured real "
            "OpenAI-compatible model. API keys are read from Settings/environment "
            "and are never printed."
        ),
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help=(
            "Run only this eval case (repeatable). Live-model mode defaults to "
            "normal_background_assessment when omitted."
        ),
    )
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
    parser.add_argument(
        "--capture-synthetic-content", action="store_true",
        help="Include sanitized model/tool content from repository evaluation fixtures in Langfuse.",
    )
    args = parser.parse_args()

    keep_dir = args.db_dir is not None
    target_dir = args.db_dir or Path(tempfile.mkdtemp(prefix="harborpilot-evals-"))
    _isolate_default_stores(target_dir)
    configure_logging()
    try:
        get_langfuse_sink()
        provider = (
            _configured_live_provider()
            if args.live_model
            else PolicyEnvelopeReplayProvider()
            if args.model_replay
            else None
        )
        mode_name = (
            "live_model"
            if args.live_model
            else "model_replay"
            if args.model_replay
            else "deterministic"
        )
        selected_ids = set(args.case_id)
        if args.live_model and not selected_ids:
            selected_ids = {"normal_background_assessment"}
        report = AgentEvalRunner(
            llm=provider,
            model_driven=provider is not None,
            mode_name=mode_name,
            capture_synthetic_content=args.capture_synthetic_content,
        ).run(selected_ids or None)
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
        shutdown_observability()
        if not keep_dir:
            shutil.rmtree(target_dir, ignore_errors=True)


def _configured_live_provider() -> OpenAICompatibleToolCallingProvider:
    """Build the same server-owned provider shape used by the Agent API."""

    from harbor_agent.config import get_settings

    settings = get_settings()
    provider = (settings.llm_provider or settings.llm_mode).lower()
    if settings.llm_mode.lower() == "openai" and provider == "mock":
        provider = "openai"
    if provider not in {"openai", "deepseek", "compatible"}:
        raise RuntimeError(
            "live-model eval requires HARBOR_AGENT_LLM_PROVIDER to be "
            "openai, deepseek or compatible"
        )
    api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "live-model eval requires HARBOR_AGENT_OPENAI_API_KEY or OPENAI_API_KEY"
        )
    base_url = settings.openai_base_url
    if provider == "deepseek":
        base_url = "https://api.deepseek.com"
    return OpenAICompatibleToolCallingProvider(
        api_key=api_key,
        model=settings.openai_model,
        provider=provider,
        base_url=base_url,
    )


if __name__ == "__main__":
    sys.exit(main())
