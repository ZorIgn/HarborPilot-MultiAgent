from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from harbor_agent.services.catalog_auto_update import CatalogAutoUpdateService
from harbor_agent.services.data_acquisition import ProgramDataAcquisitionService
from harbor_agent.models import CatalogAutoUpdateRequest, DataAcquisitionRequest
from harbor_agent.services.program_store import PROGRAM_JSON, seed_program_store, _load_program_json
from harbor_agent.services.agent_runtime import enqueue_catalog_refresh_plan
from harbor_agent.services.review_gate import build_review_queue


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run HarborPilot catalog update agents. By default this is a dry-run; "
            "use --write to persist field candidates into the local SQLite review queue."
        )
    )
    parser.add_argument("--program-id", action="append", dest="program_ids", default=[], help="Limit the update to one program id. Can be repeated.")
    parser.add_argument("--institution", default=None, help="Limit catalog URL discovery to one institution name.")
    parser.add_argument("--max-programs", type=int, default=48, help="Maximum programs scanned by the catalog auto-update agent.")
    parser.add_argument("--max-candidates-per-program", type=int, default=6, help="Maximum URL candidates kept per program.")
    parser.add_argument("--max-sources-per-program", type=int, default=8, help="Maximum acquisition source plans per program.")
    parser.add_argument("--seed", action="store_true", help="Rebuild the local SQLite program catalog before running agents.")
    parser.add_argument("--source", type=Path, default=PROGRAM_JSON, help="Program JSON source used when --seed is set.")
    parser.add_argument("--write", action="store_true", help="Persist evidence candidates to SQLite review queue. Without this flag, no writes are made.")
    parser.add_argument("--enqueue", action="store_true", help="Queue the catalog refresh agent chain instead of running it immediately.")
    parser.add_argument("--skip-data-package", action="store_true", help="Only run the catalog URL update agent.")
    args = parser.parse_args()

    seeded_count: int | None = None
    if args.seed:
        seeded_count = seed_program_store(_load_program_json(args.source), replace=True)

    dry_run = not args.write
    if args.enqueue:
        jobs = enqueue_catalog_refresh_plan(
            selected_program_ids=args.program_ids,
            institution=args.institution,
            dry_run=dry_run,
            include_community=True,
            max_programs=args.max_programs,
            max_candidates_per_program=args.max_candidates_per_program,
            max_sources_per_program=args.max_sources_per_program,
            include_data_acquisition=not args.skip_data_package,
            include_crawl_queue=not args.skip_data_package,
        )
        output = {
            "mode": "queued_write" if args.write else "queued_dry_run",
            "seeded_program_count": seeded_count,
            "jobs": jobs,
            "next_step": "Run /api/admin/agent-queue/run-next or open Admin Data Center to process jobs, then review and publish field evidence.",
        }
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
        return
    catalog_report = CatalogAutoUpdateService().run(
        CatalogAutoUpdateRequest(
            selected_program_ids=args.program_ids,
            institution=args.institution,
            dry_run=dry_run,
            max_programs=args.max_programs,
            max_candidates_per_program=args.max_candidates_per_program,
        )
    )

    data_report = None
    if not args.skip_data_package:
        data_report = ProgramDataAcquisitionService().run(
            DataAcquisitionRequest(
                selected_program_ids=args.program_ids,
                include_community=True,
                dry_run=dry_run,
                max_sources_per_program=args.max_sources_per_program,
            )
        )

    review_queue = build_review_queue(limit=80)
    output = {
        "mode": "write" if args.write else "dry_run",
        "seeded_program_count": seeded_count,
        "catalog_auto_update": {
            "run_id": catalog_report.run_id,
            "scanned_program_count": catalog_report.scanned_program_count,
            "missing_detail_page_count": catalog_report.missing_detail_page_count,
            "candidate_count": catalog_report.candidate_count,
            "persisted_candidate_count": catalog_report.persisted_candidate_count,
            "review_queue_size": catalog_report.review_queue_size,
            "warnings": catalog_report.warnings[:10],
            "summary": catalog_report.summary,
        },
        "data_acquisition": None
        if data_report is None
        else {
            "run_id": data_report.run_id,
            "package_count": len(data_report.packages),
            "source_plan_count": len(data_report.source_plan),
            "summary": data_report.summary,
        },
        "review_queue": {
            "pending_count": review_queue.pending_count,
            "returned_items": len(review_queue.items),
        },
        "next_step": "Open Admin Data Center, review field candidates, then publish only verified official fields.",
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
