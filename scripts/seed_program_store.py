from __future__ import annotations

import argparse
from pathlib import Path

from harbor_agent.services.program_store import PROGRAM_JSON, seed_program_store, _load_program_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed HarborPilot program catalog into local SQLite.")
    parser.add_argument("--source", type=Path, default=PROGRAM_JSON)
    parser.add_argument("--append", action="store_true", help="Append/update records instead of replacing the table.")
    args = parser.parse_args()

    programs = _load_program_json(args.source)
    count = seed_program_store(programs, replace=not args.append)
    print(f"seeded {count} programs from {args.source}")


if __name__ == "__main__":
    main()
