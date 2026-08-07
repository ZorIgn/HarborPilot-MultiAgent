from __future__ import annotations

"""Redaction helpers for data that crosses a runtime persistence boundary.

The runtime accepts extensible dictionaries (profile supplements, tool results,
and provider diagnostics).  Credential-looking keys therefore cannot be
handled with a fixed schema or a single spelling.  This module normalizes
camelCase, kebab-case, snake_case, and dotted keys before deciding whether a
value is sensitive, and applies the same policy recursively to mappings and
sequences.
"""

import re
from functools import lru_cache
from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import BaseModel


REDACTED_VALUE = "[redacted]"
REDACTED_TEXT = "[redacted sensitive diagnostic]"

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Keep this list deliberately specific.  ``prompt_tokens`` and
# ``total_tokens`` are observability metadata, not credentials, so a bare
# ``token`` substring must not redact those fields.
_EXACT_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "accesstoken",
    "refresh_token",
    "refreshtoken",
    "auth_token",
    "authtoken",
    "id_token",
    "idtoken",
    "csrf_token",
    "csrc_token",
    "secret",
    "password",
    "passwd",
    "passphrase",
    "authorization",
    "cookie",
    "credential",
    "credentials",
    "private_key",
    "privatekey",
    "client_secret",
    "clientsecret",
    "session_secret",
    "sessionsecret",
}


@lru_cache(maxsize=2048)
def _normalize_key_cached(text: str) -> str:
    return _NON_ALNUM.sub("_", _CAMEL_BOUNDARY.sub("_", text).lower()).strip("_")

def normalize_key(key: object) -> str:
    """Return a separator- and case-insensitive representation of a key."""

    return _normalize_key_cached(str(key))


def is_sensitive_key(key: object) -> bool:
    """Whether a dictionary key denotes a credential or secret value.

    In addition to exact spellings, compound names such as ``nestedSecret``
    and ``service-api-key`` are recognized by their normalized tokens.
    """

    normalized = normalize_key(key)
    return _is_sensitive_normalized(normalized)


@lru_cache(maxsize=2048)
def _is_sensitive_normalized(normalized: str) -> bool:
    if not normalized:
        return False
    collapsed = normalized.replace("_", "")
    if normalized in _EXACT_SENSITIVE_KEYS or collapsed in _EXACT_SENSITIVE_KEYS:
        return True
    tokens = set(normalized.split("_"))
    if "secret" in tokens or "password" in tokens or "passwd" in tokens or "passphrase" in tokens:
        return True
    if "authorization" in tokens or "credential" in tokens or "credentials" in tokens:
        return True
    if "api" in tokens and "key" in tokens:
        return True
    if ("access" in tokens or "refresh" in tokens or "auth" in tokens or "id" in tokens or "csrf" in tokens) and "token" in tokens:
        return True
    if "private" in tokens and "key" in tokens:
        return True
    return False


_SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"\bapi[\s_.-]*key\b", re.IGNORECASE),
    re.compile(r"\baccess[\s_.-]*token\b", re.IGNORECASE),
    re.compile(r"\brefresh[\s_.-]*token\b", re.IGNORECASE),
    re.compile(r"\bauth(?:orization|[\s_.-]*token)\b", re.IGNORECASE),
    re.compile(r"\b(?:password|passwd|passphrase|secret)\s*[:=]", re.IGNORECASE),
    re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    # Common provider key prefixes.  This is a last-resort guard for a
    # diagnostic string that contains a token but omits its field name.
    re.compile(r"\b(?:sk|rk|xox[baprs]|gh[psu])[-_][A-Za-z0-9._-]{12,}\b", re.IGNORECASE),
)


_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?:\bapi[\s_.-]*key\b|\baccess[\s_.-]*token\b|\brefresh[\s_.-]*token\b|"
    r"\bauth(?:orization|[\s_.-]*token)\b|\b(?:password|passwd|passphrase|secret)\s*[:=]|"
    r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}|\b(?:sk|rk|xox[baprs]|gh[psu])[-_][A-Za-z0-9._-]{12,}\b)",
    re.IGNORECASE,
)

def sanitize_text(value: object) -> str | None:
    """Redact credential-bearing diagnostic text without retaining the secret."""

    if value is None:
        return None
    text = str(value)
    if not text:
        return text
    # Split camelCase before checking bare ``secret``/``token`` words.  This
    # catches e.g. ``nestedSecret=...`` while avoiding substring matches such
    # as the ordinary word ``tokenomics``.
    normalized_text = _CAMEL_BOUNDARY.sub(" ", text)
    if _SENSITIVE_TEXT_PATTERN.search(text) or (
        normalized_text != text and _SENSITIVE_TEXT_PATTERN.search(normalized_text)
    ):
        return REDACTED_TEXT
    return text[:1600]


def sanitize_runtime_payload(value: Any) -> Any:
    """Recursively sanitize a JSON-like runtime value.

    The returned object is detached from the input and contains only values
    suitable for state/checkpoint/trace persistence.  Pydantic models and
    enums are converted to their JSON-compatible representations first.
    """

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif isinstance(value, Enum):
        value = value.value
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED_VALUE if is_sensitive_key(key) else sanitize_runtime_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [sanitize_runtime_payload(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value


# Compatibility aliases for callers/tests that used the old private helper
# name or prefer an explicit persistence-oriented name.
redact_runtime_payload = sanitize_runtime_payload
sanitize_for_persistence = sanitize_runtime_payload


__all__ = [
    "REDACTED_TEXT",
    "REDACTED_VALUE",
    "is_sensitive_key",
    "normalize_key",
    "redact_runtime_payload",
    "sanitize_for_persistence",
    "sanitize_runtime_payload",
    "sanitize_text",
]
