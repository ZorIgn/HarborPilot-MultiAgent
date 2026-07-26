"""Institution identity checks shared by acquisition and review gates.

An allow-listed university domain is not enough: a page for NUS must never be
accepted as evidence for an HKU programme with the same title.  These helpers
bind a source to the expected institution root while still allowing official
subdomains such as admissions.hku.hk and msc.cse.cuhk.edu.hk.
"""

from __future__ import annotations

from urllib.parse import urlparse


OFFICIAL_SCHOOL_DOMAINS = {
    "hku.hk",
    "cuhk.edu.hk",
    "hkust.edu.hk",
    "ust.hk",
    "cityu.edu.hk",
    "polyu.edu.hk",
    "hkbu.edu.hk",
    "ln.edu.hk",
    "eduhk.hk",
    "nus.edu.sg",
    "ntu.edu.sg",
    "smu.edu.sg",
    "sutd.edu.sg",
}


def official_institution_domain(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(str(url))
    if parsed.scheme != "https":
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    for domain in sorted(OFFICIAL_SCHOOL_DOMAINS, key=len, reverse=True):
        if host == domain or host.endswith("." + domain):
            return domain
    return None


def is_allowed_official_url(url: str | None) -> bool:
    return official_institution_domain(url) is not None


def same_official_institution(actual_url: str | None, expected_url: str | None) -> bool:
    actual = official_institution_domain(actual_url)
    expected = official_institution_domain(expected_url)
    if actual or expected:
        return bool(actual and expected and actual == expected)
    actual_host = (urlparse(str(actual_url or "")).hostname or "").lower().rstrip(".")
    expected_host = (urlparse(str(expected_url or "")).hostname or "").lower().rstrip(".")
    return bool(actual_host and expected_host and actual_host == expected_host)
