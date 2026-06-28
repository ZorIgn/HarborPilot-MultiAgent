from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GLOBS = [
    "README.md",
    "docs/**/*.md",
    "src/harbor_agent/**/*.py",
    "web/app/**/*.tsx",
    "web/lib/**/*.ts",
    "tests/**/*.py",
]
SKIP_PARTS = {
    ".git",
    ".next",
    ".venv",
    "node_modules",
    "__pycache__",
}
MOJIBAKE_MARKERS = [
    "\ufffd",
    "????",
    "\u7ec0\u60e7",
    "\u701b\ufe3d",
    "\u9422\u5ba0",
    "\u93c9\u30e6",
    "\u5bf0\u546f",
    "\u9359\ue219",
    "\u93c3\u5815",
    "\u93cd\u7a3f",
    "\u95c2\u3127",
    "\u9286",
    "\u951b",
    "\u9225",
]


@dataclass(frozen=True)
class TextQualityFinding:
    path: str
    line: int
    marker: str
    preview: str


def iter_candidate_paths(patterns: list[str]) -> list[Path]:
    paths: set[Path] = set()
    for pattern in patterns:
        for path in ROOT.glob(pattern):
            if not path.is_file():
                continue
            if any(part in SKIP_PARTS for part in path.parts):
                continue
            paths.add(path)
    return sorted(paths)


def scan_file(path: Path) -> list[TextQualityFinding]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return [
            TextQualityFinding(
                path=str(path.relative_to(ROOT)).replace("\\", "/"),
                line=0,
                marker="UNICODE_DECODE_ERROR",
                preview=str(exc),
            )
        ]

    findings: list[TextQualityFinding] = []
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    for lineno, line in enumerate(text.splitlines(), start=1):
        for marker in MOJIBAKE_MARKERS:
            if marker in line:
                findings.append(
                    TextQualityFinding(
                        path=rel,
                        line=lineno,
                        marker=marker,
                        preview=line.strip()[:180],
                    )
                )
                break
    return findings


def scan(patterns: list[str]) -> list[TextQualityFinding]:
    findings: list[TextQualityFinding] = []
    for path in iter_candidate_paths(patterns):
        findings.extend(scan_file(path))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Chinese text for mojibake and UTF-8 decode problems.")
    parser.add_argument("paths", nargs="*", help="Optional glob patterns relative to the repo root.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--fail", action="store_true", help="Exit non-zero when findings exist.")
    parser.add_argument("--limit", type=int, default=80, help="Maximum findings to print in text mode.")
    args = parser.parse_args()

    findings = scan(args.paths or DEFAULT_GLOBS)
    if args.json:
        print(json.dumps([asdict(item) for item in findings], ensure_ascii=False, indent=2))
    else:
        print(f"Scanned text quality: {len(findings)} finding(s).")
        by_path: dict[str, int] = {}
        for item in findings:
            by_path[item.path] = by_path.get(item.path, 0) + 1
        for path, count in sorted(by_path.items(), key=lambda entry: (-entry[1], entry[0]))[: args.limit]:
            print(f"{count:4d}  {path}")
        if findings:
            print("\nSample findings:")
            for item in findings[: args.limit]:
                print(f"{item.path}:{item.line}: {repr(item.marker)} :: {item.preview}")
    return 1 if args.fail and findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
