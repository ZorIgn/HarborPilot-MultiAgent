from __future__ import annotations

from harbor_agent.services import source_snapshot
from harbor_agent.services.source_snapshot import snapshot_source


def test_source_snapshot_rejects_local_and_non_https_urls_before_fetch() -> None:
    for url in [
        "http://www.hku.hk/programme",
        "https://127.0.0.1/admin",
        "https://localhost/internal",
        "https://10.0.0.8/source",
        "https://www.hku.hk:8443/programme",
    ]:
        result = snapshot_source(url, dry_run=True)
        assert result.ok is False
        assert result.status == "UNSAFE_URL_REJECTED"


def test_source_snapshot_does_not_treat_antibot_shell_as_success(monkeypatch, tmp_path) -> None:
    body = b"<html><script src='/_Incapsula_Resource'></script><body></body></html>"
    monkeypatch.setattr(source_snapshot, "_write_snapshot", lambda *args, **kwargs: str(tmp_path / "challenge.html"))
    monkeypatch.setattr(source_snapshot, "_unsafe_url_reason", lambda url: None)
    monkeypatch.setattr(source_snapshot, "_robots_allowed", lambda url: True)
    monkeypatch.setattr(source_snapshot, "_fetch_with_playwright", lambda url: None)
    monkeypatch.setattr(
        source_snapshot,
        "_fetch_with_urllib",
        lambda url: (200, "text/html", body, url),
    )

    result = snapshot_source("https://www.cityu.edu.hk/pg/programme/p53")

    assert result.ok is False
    assert result.status == "CONTENT_REVIEW_REQUIRED"
    assert "anti-bot" in str(result.error)
    assert result.page_hash
    assert result.snapshot_path
