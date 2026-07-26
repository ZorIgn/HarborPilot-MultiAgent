from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib import robotparser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener

from harbor_agent.models import FieldEvidenceRecord, FieldExtractionCandidate, FieldVerificationStatus, SourceScope, SourceTrustLevel
from harbor_agent.services.data_loader import DATA_DIR

USER_AGENT = "HarborPilotAI/0.1 admissions-source-snapshot (+human review)"
MAX_BYTES = 1_500_000
SNAPSHOT_DIR = DATA_DIR / "source_snapshots"


@dataclass(frozen=True)
class SnapshotResult:
    ok: bool
    url: str
    status: str
    checked_at: datetime
    http_status: int | None = None
    page_hash: str | None = None
    snapshot_path: str | None = None
    snapshot_mime: str | None = None
    content_bytes: int = 0
    text: str = ""
    error: str | None = None
    robots_url: str | None = None
    robots_allowed: bool | None = None
    final_url: str | None = None
    page_title: str | None = None
    attempts: int = 0
    duration_ms: int = 0
    html: str = ""


def _fetch_with_playwright(url: str) -> tuple[int, str, bytes, str] | None:
    if os.getenv("HARBORPILOT_USE_PLAYWRIGHT", "0").lower() not in {"1", "true", "yes"}:
        return None
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        return None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(user_agent=USER_AGENT)
            def guard_route(route):
                reason = _unsafe_url_reason(route.request.url)
                route.abort() if reason else route.continue_()
            page.route("**/*", guard_route)
            response = page.goto(url, wait_until="networkidle", timeout=20_000)
            if _unsafe_url_reason(page.url):
                raise ValueError("browser navigation redirected to an unsafe URL")
            html = page.content().encode("utf-8", errors="ignore")[:MAX_BYTES]
            status = int(response.status) if response else 200
            final_url = page.url
            browser.close()
            return status, "text/html; rendered=playwright", html, final_url
    except Exception:
        return None


def _fetch_with_urllib(url: str) -> tuple[int, str, bytes, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    opener = build_opener(_SafeRedirectHandler())
    with opener.open(request, timeout=18) as response:
        return (
            int(getattr(response, "status", 200)),
            str(response.headers.get("content-type") or "").lower(),
            response.read(MAX_BYTES),
            str(getattr(response, "url", url) or url),
        )


def snapshot_source(
    url: str,
    *,
    dry_run: bool = False,
    checked_at: datetime | None = None,
    max_attempts: int = 2,
) -> SnapshotResult:
    checked = checked_at or datetime.now(UTC)
    started = time.perf_counter()
    unsafe_reason = _unsafe_url_reason(url)
    if unsafe_reason:
        return SnapshotResult(
            ok=False,
            url=url,
            status="UNSAFE_URL_REJECTED",
            checked_at=checked,
            error=unsafe_reason,
            final_url=url,
            attempts=0,
            duration_ms=_elapsed_ms(started),
        )
    if dry_run:
        return SnapshotResult(
            ok=False,
            url=url,
            status="SKIPPED_DRY_RUN",
            checked_at=checked,
            robots_url=_robots_url(url),
            final_url=url,
            attempts=0,
            duration_ms=_elapsed_ms(started),
        )
    robots_allowed = _robots_allowed(url)
    if robots_allowed is False:
        return SnapshotResult(
            ok=False,
            url=url,
            status="ROBOTS_REVIEW_REQUIRED",
            checked_at=checked,
            robots_url=_robots_url(url),
            robots_allowed=False,
            error="robots.txt does not allow automated fetch for this user agent",
            final_url=url,
            attempts=0,
            duration_ms=_elapsed_ms(started),
        )
    attempts = 0
    last_error: Exception | None = None
    http_status = None
    content_type = ""
    body = b""
    final_url = url
    for attempt in range(1, max(1, min(int(max_attempts), 3)) + 1):
        attempts = attempt
        try:
            rendered = _fetch_with_playwright(url)
            if rendered is None:
                http_status, content_type, body, final_url = _fetch_with_urllib(url)
            else:
                http_status, content_type, body, final_url = rendered
            # A redirect is a new trust decision, not merely a transport detail.
            redirect_reason = _unsafe_url_reason(final_url)
            if redirect_reason:
                raise ValueError(f"redirected source is unsafe: {redirect_reason}")
            break
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
            if attempt < max(1, min(int(max_attempts), 3)):
                time.sleep(0.15 * (2 ** (attempt - 1)))
    if last_error is not None and not body:
        exc = last_error
        return SnapshotResult(
            ok=False,
            url=url,
            status="FETCH_FAILED",
            checked_at=checked,
            robots_url=_robots_url(url),
            robots_allowed=robots_allowed,
            error=f"{type(exc).__name__}: {exc}",
            final_url=final_url,
            attempts=attempts,
            duration_ms=_elapsed_ms(started),
        )
    page_hash = "sha256:" + hashlib.sha256(body).hexdigest()
    mime = _mime_from(content_type, url, body)
    snapshot_path = _write_snapshot(url, body, checked, page_hash, mime)
    text = _extract_text(body, mime)
    html = body.decode("utf-8", errors="ignore") if mime != "application/pdf" else ""
    content_error = _content_rejection_reason(body, mime)
    transport_ok = bool(http_status is not None and http_status < 400)
    return SnapshotResult(
        ok=transport_ok and content_error is None,
        url=url,
        status=(
            "CONTENT_REVIEW_REQUIRED"
            if transport_ok and content_error
            else ("FETCH_OK" if transport_ok else "REVIEW_REQUIRED")
        ),
        checked_at=checked,
        http_status=http_status,
        page_hash=page_hash,
        snapshot_path=snapshot_path,
        snapshot_mime=mime,
        content_bytes=len(body),
        text=text,
        error=content_error,
        robots_url=_robots_url(url),
        robots_allowed=robots_allowed,
        final_url=final_url,
        page_title=_extract_title(html),
        attempts=attempts,
        duration_ms=_elapsed_ms(started),
        html=html,
    )


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        unsafe_reason = _unsafe_url_reason(newurl)
        if unsafe_reason:
            raise URLError(unsafe_reason)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _unsafe_url_reason(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "only HTTPS official sources are allowed"
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".local"):
        return "source hostname is missing or local"
    if parsed.port not in {None, 443}:
        return "non-standard source ports are not allowed"
    try:
        literal = ipaddress.ip_address(host)
        return None if literal.is_global else "private or reserved IP addresses are not allowed"
    except ValueError:
        pass
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        return f"source hostname could not be resolved: {exc}"
    if not addresses or any(not address.is_global for address in addresses):
        return "source resolved to a private or reserved network address"
    return None


def _content_rejection_reason(body: bytes, mime: str) -> str | None:
    if mime == "application/pdf":
        return None
    sample = body[:200_000].decode("utf-8", errors="ignore").lower()
    challenge_markers = {
        "_incapsula_resource": "anti-bot challenge page (Incapsula)",
        "cf-chl-": "anti-bot challenge page (Cloudflare)",
        "captcha": "captcha challenge page",
        "verify you are human": "human-verification challenge page",
        "access denied": "access-denied response page",
    }
    for marker, reason in challenge_markers.items():
        if marker in sample:
            return reason
    return None


def extract_field_candidates(text: str) -> list[FieldExtractionCandidate]:
    cleaned = _normalize_space(text)
    candidates = [
        _deadline_candidate(cleaned),
        _tuition_candidate(cleaned),
        _language_candidate(cleaned),
        _materials_candidate(cleaned),
        _application_candidate(cleaned),
        _essay_candidate(cleaned),
    ]
    return [candidate for candidate in candidates if candidate is not None]


def evidence_records_from_candidates(
    *,
    program_id: str,
    cycle: str,
    source_url: str,
    source_type: str,
    snapshot: SnapshotResult,
    candidates: Iterable[FieldExtractionCandidate],
    trust_level: SourceTrustLevel | str,
    source_scope: SourceScope | None = None,
    page_title: str | None = None,
    final_url: str | None = None,
    binding_status: str = "not_checked",
    binding_score: int = 0,
) -> list[FieldEvidenceRecord]:
    priority = 1 if str(trust_level) == SourceTrustLevel.official.value or trust_level == SourceTrustLevel.official else 8
    records: list[FieldEvidenceRecord] = []
    for candidate in candidates:
        if candidate.value is None:
            continue
        records.append(
            FieldEvidenceRecord(
                program_id=program_id,
                field_name=candidate.field_name,
                value=candidate.value,
                cycle=cycle,
                source_url=source_url,
                source_type=source_type,
                extracted_at=snapshot.checked_at,
                verified_at=None,
                page_hash=snapshot.page_hash,
                confidence=candidate.confidence,
                source_priority=priority,
                status=FieldVerificationStatus.official_previous_cycle,
                review_required=True,
                evidence_snippet=candidate.evidence_snippet,
                snapshot_url=snapshot.snapshot_path,
                agent_chain=[
                    "SourceDiscoveryAgent",
                    "SnapshotCrawlerAgent",
                    "HtmlPdfTextExtractionAgent",
                    "FieldCandidateAgent",
                    "HumanReviewGateAgent",
                ],
                source_scope=source_scope,
                page_title=page_title,
                final_url=final_url,
                binding_status=binding_status,
                binding_score=binding_score,
            )
        )
    return records


def discovered_links(html_or_text: str, base_url: str, limit: int = 30) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r'href=["\']([^"\']+)["\']', html_or_text, re.IGNORECASE):
        href = unescape(match.group(1).strip())
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base_url, href)
        low = full.lower()
        if not any(token in low for token in ["program", "programme", "admission", "apply", "master", "msc", "graduate", "pdf"]):
            continue
        if full in seen:
            continue
        seen.add(full)
        links.append(full)
        if len(links) >= limit:
            break
    return links


def _robots_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


def _robots_allowed(url: str) -> bool | None:
    robots_url = _robots_url(url)
    if not robots_url:
        return None
    try:
        status, _, body, _ = _fetch_with_urllib(robots_url)
        if status >= 400:
            return None
    except Exception:
        return None
    parser = robotparser.RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(body.decode("utf-8", errors="ignore").splitlines())
    try:
        return parser.can_fetch(USER_AGENT, url)
    except Exception:
        return None


def _write_snapshot(url: str, body: bytes, checked_at: datetime, page_hash: str, mime: str) -> str:
    date_dir = SNAPSHOT_DIR / checked_at.strftime("%Y%m%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".pdf" if mime == "application/pdf" else ".html"
    host = re.sub(r"[^a-zA-Z0-9_.-]+", "_", urlparse(url).netloc or "source")[:48]
    name = f"{checked_at.strftime('%H%M%S')}_{host}_{page_hash.split(':', 1)[1][:12]}{suffix}"
    path = date_dir / name
    path.write_bytes(body)
    return str(path.relative_to(DATA_DIR.parent)).replace("\\", "/")


def _mime_from(content_type: str, url: str, body: bytes) -> str:
    low_url = url.lower()
    if "pdf" in content_type or low_url.endswith(".pdf") or body.startswith(b"%PDF"):
        return "application/pdf"
    if "html" in content_type or b"<html" in body[:2048].lower():
        return "text/html"
    return content_type.split(";", 1)[0] or "application/octet-stream"


def _extract_text(body: bytes, mime: str) -> str:
    if mime == "application/pdf":
        extracted = _extract_pdf_text(body)
        if extracted.strip():
            return extracted
    decoded = body.decode("utf-8", errors="ignore")
    if "<" in decoded and ">" in decoded:
        return _html_to_text(decoded)
    return _normalize_space(decoded)


def _extract_pdf_text(body: bytes) -> str:
    try:
        from io import BytesIO
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(BytesIO(body))
        return "\n".join(page.extract_text() or "" for page in reader.pages[:20])
    except Exception:
        try:
            from io import BytesIO
            from PyPDF2 import PdfReader  # type: ignore

            reader = PdfReader(BytesIO(body))
            return "\n".join(page.extract_text() or "" for page in reader.pages[:20])
        except Exception:
            return ""


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|li|tr|h[1-6])>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", html)
    return _normalize_space(unescape(text))


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _extract_title(html: str) -> str | None:
    if not html:
        return None
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if not match:
        return None
    title = _normalize_space(unescape(match.group(1)))
    return title[:240] or None


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _snippet(text: str, pattern: str, window: int = 180) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    start = max(0, match.start() - window // 3)
    end = min(len(text), match.end() + window)
    return _normalize_space(text[start:end])[:360]


def _deadline_candidate(text: str) -> FieldExtractionCandidate | None:
    snippet = _snippet(text, "deadline|closing date|application closes|application deadline|round [123]|\u622a\u6b62|\u7533\u8bf7\u622a\u6b62")
    if not snippet:
        return None
    date = re.search(r"20[2-9][0-9][-/\. ]+[01]?[0-9][-/\. ]+[0-3]?[0-9]|[0-3]?[0-9]\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20[2-9][0-9]", snippet, re.IGNORECASE)
    return FieldExtractionCandidate(field_name="deadline", value=date.group(0) if date else None, evidence_snippet=snippet, confidence="medium" if date else "low")


def _tuition_candidate(text: str) -> FieldExtractionCandidate | None:
    snippet = _snippet(text, "tuition|programme fee|program fee|application fee|\u5b66\u8d39|\u8d39\u7528")
    if not snippet:
        return None
    amount = re.search(
        r"(?P<currency>HK\$|HKD|S\$|SGD|USD|RMB|CNY)\s*(?P<amount>[0-9][0-9,]{3,})",
        snippet,
        re.IGNORECASE,
    )
    if amount is None:
        amount = re.search(
            r"(?P<currency>)(?P<amount>[0-9][0-9,]{3,})(?=\s*(?:per\s+year|tuition|fee|学费|费用))",
            snippet,
            re.IGNORECASE,
        )
    if not amount:
        return FieldExtractionCandidate(
            field_name="tuition_original",
            value=None,
            evidence_snippet=snippet,
            confidence="low",
        )
    currency = (amount.group("currency") or "UNSPECIFIED").upper()
    value = f"{currency} {amount.group('amount')}"
    # Never put SGD/USD/RMB or an unspecified amount into a field whose unit
    # contract is explicitly HKD. Currency conversion requires a separate
    # rate source and conversion timestamp.
    field_name = "tuition_hkd" if currency in {"HK$", "HKD"} else "tuition_original"
    return FieldExtractionCandidate(
        field_name=field_name,
        value=value,
        evidence_snippet=snippet,
        confidence="medium",
    )


def _language_candidate(text: str) -> FieldExtractionCandidate | None:
    snippet = _snippet(text, "IELTS|TOEFL|PTE|English language|language requirement|\u96c5\u601d|\u6258\u798f|\u82f1\u8bed")
    if not snippet:
        return None
    return FieldExtractionCandidate(field_name="language_requirement", value=snippet[:220], evidence_snippet=snippet, confidence="medium")


def _materials_candidate(text: str) -> FieldExtractionCandidate | None:
    snippet = _snippet(text, "transcript|recommendation|personal statement|CV|resume|supporting document|\u6210\u7ee9\u5355|\u63a8\u8350\u4fe1|\u4e2a\u4eba\u9648\u8ff0|\u7b80\u5386|\u6750\u6599")
    if not snippet:
        return None
    return FieldExtractionCandidate(field_name="materials", value=snippet[:260], evidence_snippet=snippet, confidence="medium")


def _application_candidate(text: str) -> FieldExtractionCandidate | None:
    snippet = _snippet(text, "online application|application system|apply now|apply online|submit application|\u7f51\u7533|\u7533\u8bf7\u7cfb\u7edf|\u7acb\u5373\u7533\u8bf7")
    if not snippet:
        return None
    return FieldExtractionCandidate(field_name="application_url", value=None, evidence_snippet=snippet, confidence="low")


def _essay_candidate(text: str) -> FieldExtractionCandidate | None:
    snippet = _snippet(
        text,
        "personal statement|statement of purpose|admission essay|essay question|writing sample|"
        "\u4e2a\u4eba\u9648\u8ff0|\u7533\u8bf7\u6587\u4e66|\u6587\u4e66\u9898\u76ee",
    )
    if not snippet:
        return None
    return FieldExtractionCandidate(field_name="essay_prompts", value=snippet[:260], evidence_snippet=snippet, confidence="medium")
