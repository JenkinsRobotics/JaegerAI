"""Secret redaction for logs, tool outputs, and outbound channel messages.

Adapted from NousResearch/hermes-agent `agent/redact.py` (MIT License).
Short tokens (< 18 chars) are fully masked; longer ones preserve only the first
6 and last 4 characters for operator debuggability without leaking credentials.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACT_WALK_MAX_DEPTH = 128
REDACT_WALK_DEPTH_MARKER = "[redacted: nesting limit]"

SENSITIVE_QUERY_PARAMS = frozenset({
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "api_key",
    "apikey",
    "client_secret",
    "password",
    "auth",
    "jwt",
    "session",
    "secret",
    "key",
    "code",
    "signature",
    "x-amz-signature",
    "x-goog-signature",
    "sig",
})

_PREFIX_PATTERNS = (
    r"sk-[A-Za-z0-9_-](?:\.?[A-Za-z0-9_-]){9,}",
    r"ctx7sk-[A-Za-z0-9_-]{10,}",
    r"ghp_[A-Za-z0-9]{10,}",
    r"github_pat_[A-Za-z0-9_]{10,}",
    r"gho_[A-Za-z0-9]{10,}",
    r"ghu_[A-Za-z0-9]{10,}",
    r"ghs_[A-Za-z0-9]{10,}",
    r"ghr_[A-Za-z0-9]{10,}",
    r"xapp-\d+-[A-Za-z0-9-]{10,}",
    r"xox[baprs]-[A-Za-z0-9-]{10,}",
    r"AIza[A-Za-z0-9_-]{30,}",
    r"GOCSPX-[A-Za-z0-9_-]{8,}",
    r"ya29\.(?:[a-z]\.)?[A-Za-z0-9_-]{20,}",
    r"AQ\.[A-Za-z0-9_-]{30,}",
    r"1//0[A-Za-z0-9_-]{20,}",
    r"pplx-[A-Za-z0-9]{10,}",
    r"fal_[A-Za-z0-9_-]{10,}",
    r"fc-[A-Za-z0-9]{10,}",
    r"AKIA[A-Z0-9]{16}",
    r"sk_live_[A-Za-z0-9]{10,}",
    r"sk_test_[A-Za-z0-9]{10,}",
    r"rk_live_[A-Za-z0-9]{10,}",
    r"SG\.[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]{10,})?",
    r"hf_[A-Za-z0-9]{10,}",
    r"r8_[A-Za-z0-9]{10,}",
    r"npm_[A-Za-z0-9]{10,}",
    r"pypi-[A-Za-z0-9_-]{10,}",
    r"sk_[A-Za-z0-9_]{10,}",
    r"tvly-(?:(?:dev|prod)-)?[A-Za-z0-9]{10,}",
    r"exa_[A-Za-z0-9]{10,}",
    r"gsk_[A-Za-z0-9]{10,}",
    r"xai-[A-Za-z0-9]{20,}",
    r"ntn_[A-Za-z0-9]{10,}",
    r"glpat-[A-Za-z0-9_\-]{10,}",
)

_PREFIX_RE = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(_PREFIX_PATTERNS) + r")")
_PEM_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z0-9 ]*PRIVATE KEY-----"
)
_AUTH_HDR_RE = re.compile(
    r"(?i)(\b(?:authorization|x-api-key|api-key)\s*[:=]\s*(?:bearer\s+|basic\s+)?)([A-Za-z0-9._\-+/=]{12,})"
)
_KV_SECRET_RE = re.compile(
    r"(?i)(\b[A-Z0-9_]*(?:API_KEY|SECRET_KEY|ACCESS_TOKEN|REFRESH_TOKEN|CLIENT_SECRET|PRIVATE_KEY|PASSWORD|AUTH_TOKEN)\b\s*[:=]\s*['\"]?)([^\s'\",;&]{8,})"
)
_URL_RE = re.compile(r"https?://[^\s'\"<>]+")


def _mask_token(tok: str) -> str:
    if len(tok) < 18:
        return "***REDACTED***"
    return f"{tok[:6]}...{tok[-4:]}"


def _scrub_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    try:
        parts = urlsplit(raw)
        if not parts.query:
            return raw
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        changed = False
        new_pairs: list[tuple[str, str]] = []
        for k, v in pairs:
            if k.lower() in SENSITIVE_QUERY_PARAMS and v:
                new_pairs.append((k, "REDACTED"))
                changed = True
            else:
                new_pairs.append((k, v))
        if not changed:
            return raw
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(new_pairs), parts.fragment))
    except Exception:  # noqa: BLE001
        return raw


def redact_text(text: str) -> str:
    """Scrub API keys, bearer headers, private keys, and sensitive URL query params."""
    if not text:
        return text
    out = _PEM_RE.sub("[REDACTED PRIVATE KEY]", text)
    out = _URL_RE.sub(_scrub_url, out)
    out = _AUTH_HDR_RE.sub(lambda m: f"{m.group(1)}{_mask_token(m.group(2))}", out)
    out = _KV_SECRET_RE.sub(lambda m: f"{m.group(1)}{_mask_token(m.group(2))}", out)
    out = _PREFIX_RE.sub(lambda m: _mask_token(m.group(1)), out)
    return out


def redact_object(value: Any, *, _depth: int = 0) -> Any:
    """Recursively redact strings inside dicts/lists/tuples with depth protection."""
    if _depth >= REDACT_WALK_MAX_DEPTH:
        return REDACT_WALK_DEPTH_MARKER
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            ks = str(k).lower()
            if isinstance(v, str) and any(s in ks for s in ("secret", "token", "password", "api_key", "apikey", "private_key")):
                out[k] = _mask_token(v) if v else v
            else:
                out[k] = redact_object(v, _depth=_depth + 1)
        return out
    if isinstance(value, list):
        return [redact_object(item, _depth=_depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_object(item, _depth=_depth + 1) for item in value)
    return value


__all__ = ["SENSITIVE_QUERY_PARAMS", "redact_object", "redact_text"]
