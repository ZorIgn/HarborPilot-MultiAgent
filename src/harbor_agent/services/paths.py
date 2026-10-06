"""Separate immutable catalog seeds from persistent application state."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SEED_DIR = Path(os.environ.get("HARBOR_AGENT_SEED_DIR", ROOT / "data"))
DATA_DIR = Path(os.environ.get("HARBOR_AGENT_DATA_DIR", ROOT / "data"))


def seed_path(name: str) -> Path:
    override = DATA_DIR / name
    return override if override.is_file() else SEED_DIR / name
