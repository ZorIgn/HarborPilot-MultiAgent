from __future__ import annotations

import argparse
import json
import sys

from harbor_agent.evals.runner import AgentEvalRunner


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run deterministic HarborPilot Agent Evals.")
    parser.add_argument(
        "--include-trace",
        action="store_true",
        help="Print full per-case runtime traces (disabled by default to keep CI logs readable).",
    )
    args = parser.parse_args()

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
    sys.exit(0 if all(item["passed"] for item in report["results"]) else 1)
