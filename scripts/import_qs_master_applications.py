from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = ROOT / ".agents" / "qs-master-applications"
DEFAULT_OUTPUT = ROOT / "data" / "external_candidates" / "qs_master_applications_candidates.json"

PROGRAM_HINTS = ("master", "msc", "ma ", "meng", "mcomp", "programme", "program", "硕士")
URL_RE = re.compile(r"https?://[^\s)\"'>]+", re.IGNORECASE)
DATE_RE = re.compile(
    r"20[2-9][0-9][-/.\s年]+[01]?[0-9][-/.\s月]+[0-3]?[0-9]"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+[0-3]?[0-9],?\s+20[2-9][0-9]",
    re.IGNORECASE,
)


def main() -> None:
    repo = DEFAULT_REPO
    output = DEFAULT_OUTPUT
    if not repo.exists():
        existing = _read_existing_import(output)
        if existing.get("status") == "ok" and existing.get("candidates"):
            result = {
                "status": "already_imported",
                "message": "已存在可用的 GradWindow / QS Master Applications 本地导入包，未覆盖。",
                "candidate_count": existing.get("candidate_count", len(existing.get("candidates", []))),
                "output": str(output),
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        result = {
            "source_id": "qs_master_applications_github",
            "source_url": "https://github.com/lione12138/qs-master-applications",
            "status": "repo_not_found",
            "message": (
                "未找到 .agents/qs-master-applications。请先执行 "
                "git clone https://github.com/lione12138/qs-master-applications.git .agents/qs-master-applications"
            ),
            "candidates": [],
        }
        _write_json(output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    candidates = _scan_repository(repo)
    result = {
        "source_id": "qs_master_applications_github",
        "source_name": "GradWindow / QS Master Applications",
        "source_url": "https://github.com/lione12138/qs-master-applications",
        "status": "ok",
        "repo_path": str(repo),
        "candidate_count": len(candidates),
        "policy": (
            "这些记录只能作为项目发现、官网链接候选和日期线索。"
            "截止日期、学费、语言、材料、申请入口必须回到学校官网确认。"
        ),
        "candidates": candidates,
    }
    _write_json(output, result)
    print(json.dumps({"status": "ok", "candidate_count": len(candidates), "output": str(output)}, ensure_ascii=False))


def _scan_repository(repo: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for path in repo.rglob("*"):
        if path.is_dir() or _skip_path(path):
            continue
        try:
            if path.suffix.lower() == ".json":
                candidates.extend(_from_json(path, repo))
            elif path.suffix.lower() == ".csv":
                candidates.extend(_from_csv(path, repo))
            elif path.suffix.lower() in {".md", ".txt"}:
                candidates.extend(_from_text(path, repo))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, csv.Error) as exc:
            candidates.append(
                {
                    "source_file": str(path.relative_to(repo)),
                    "record_type": "parse_error",
                    "error": type(exc).__name__,
                    "official_url_candidates": [],
                    "date_candidates": [],
                    "review_required": True,
                }
            )
    return _dedupe_candidates(candidates)


def _from_json(path: Path, repo: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else _flatten_json_rows(data)
    return [_candidate_from_mapping(row, path, repo) for row in rows if isinstance(row, dict)]


def _flatten_json_rows(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        rows: list[Any] = []
        for value in data.values():
            if isinstance(value, list):
                rows.extend(value)
            elif isinstance(value, dict):
                rows.append(value)
        return rows
    return []


def _from_csv(path: Path, repo: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [_candidate_from_mapping(row, path, repo) for row in csv.DictReader(file)]


def _from_text(path: Path, repo: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    candidates: list[dict[str, Any]] = []
    for index, line in enumerate(text.splitlines(), start=1):
        if not _looks_like_program_line(line):
            continue
        candidates.append(
            {
                "source_file": str(path.relative_to(repo)),
                "source_line": index,
                "record_type": "text_line",
                "institution": _guess_institution(line),
                "program_name": _trim(line),
                "official_url_candidates": URL_RE.findall(line),
                "date_candidates": DATE_RE.findall(line),
                "raw": line[:500],
                "review_required": True,
            }
        )
    return candidates


def _candidate_from_mapping(row: dict[str, Any], path: Path, repo: Path) -> dict[str, Any]:
    text = " ".join(str(value) for value in row.values() if value is not None)
    return {
        "source_file": str(path.relative_to(repo)),
        "record_type": "structured_row",
        "institution": _pick(row, ["institution", "university", "school", "college", "院校", "学校"]),
        "program_name": _pick(row, ["program", "programme", "major", "name", "title", "项目", "专业"]),
        "region": _pick(row, ["region", "country", "location", "地区", "国家"]),
        "official_url_candidates": _urls_from_row(row, text),
        "date_candidates": DATE_RE.findall(text),
        "raw": {str(key): value for key, value in row.items()},
        "review_required": True,
    }


def _urls_from_row(row: dict[str, Any], text: str) -> list[str]:
    urls = set(URL_RE.findall(text))
    for key, value in row.items():
        if value and any(token in str(key).lower() for token in ["url", "link", "website", "官网", "链接"]):
            urls.update(URL_RE.findall(str(value)))
    return sorted(urls)


def _pick(row: dict[str, Any], keys: list[str]) -> str | None:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in {None, ""}:
            return str(value).strip()
    return None


def _looks_like_program_line(line: str) -> bool:
    lowered = line.lower()
    return any(hint in lowered for hint in PROGRAM_HINTS) and (URL_RE.search(line) or DATE_RE.search(line))


def _guess_institution(line: str) -> str | None:
    match = re.search(r"(HKU|CUHK|HKUST|CityU|PolyU|HKBU|Lingnan|NUS|NTU|SMU|SUTD)", line, re.IGNORECASE)
    return match.group(1) if match else None


def _dedupe_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = "|".join(
            [
                str(item.get("source_file", "")),
                str(item.get("institution", "")),
                str(item.get("program_name", "")),
                ",".join(item.get("official_url_candidates", [])),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _trim(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:240]


def _skip_path(path: Path) -> bool:
    return any(part in {".git", "node_modules", ".next", "dist", "build"} for part in path.parts)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_existing_import(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


if __name__ == "__main__":
    main()
