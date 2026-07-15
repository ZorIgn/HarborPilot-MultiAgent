from __future__ import annotations

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
