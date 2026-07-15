from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from harbor_agent.services.agent_runtime import enqueue_catalog_refresh_plan
from harbor_agent.services.agent_worker import run_agent_worker_loop
from harbor_agent.services.review_gate import build_review_queue


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run queued HarborPilot agents locally. This can process catalog URL discovery, "
            "data acquisition, crawl-queue planning, matching, timeline, and scenario-audit jobs."
        )
    )
    parser.add_argument("--max-jobs", type=int, default=20, help="Maximum queued jobs to process before exiting.")
    parser.add_argument("--poll-interval", type=float, default=0.0, help="Seconds to wait between processed jobs.")
    parser.add_argument("--assigned-to", default="local_agent_worker", help="Worker name written to the agent queue.")
    parser.add_argument("--enqueue-catalog-refresh", action="store_true", help="Queue catalog_auto_update + data_acquisition + crawl_queue before processing.")
    parser.add_argument("--program-id", action="append", dest="program_ids", default=[], help="Limit queued refresh to one program id. Can be repeated.")
    parser.add_argument("--institution", default=None, help="Limit queued refresh to one institution name.")
    parser.add_argument("--write", action="store_true", help="Allow update agents to write review candidates. Student-visible fields still require review publish.")
    parser.add_argument("--max-programs", type=int, default=48, help="Maximum programs scanned when enqueueing refresh.")
    parser.add_argument("--max-candidates-per-program", type=int, default=6, help="URL candidates kept per program.")
    parser.add_argument("--max-sources-per-program", type=int, default=8, help="Source plans kept per program.")
    args = parser.parse_args()

    queued = []
    if args.enqueue_catalog_refresh:
        queued = enqueue_catalog_refresh_plan(
            selected_program_ids=args.program_ids,
            institution=args.institution,
            dry_run=not args.write,
            include_community=True,
            max_programs=args.max_programs,
            max_candidates_per_program=args.max_candidates_per_program,
            max_sources_per_program=args.max_sources_per_program,
            include_data_acquisition=True,
            include_crawl_queue=True,
        )

    result = run_agent_worker_loop(
        max_jobs=args.max_jobs,
        poll_interval_seconds=args.poll_interval,
        assigned_to=args.assigned_to,
    )
    review_queue = build_review_queue(limit=80)
    print(json.dumps({
        "queued_job_count": len(queued),
        "queued_jobs": queued,
        "worker": result,
        "review_queue": {
            "pending_count": review_queue.pending_count,
            "publishable_count": review_queue.publishable_count,
            "returned_items": len(review_queue.items),
        },
        "next_step": "Open Admin Data Center, approve only verified official fields, then publish them to student-facing trust records.",
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
