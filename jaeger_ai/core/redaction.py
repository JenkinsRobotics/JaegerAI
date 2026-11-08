"""Mandatory redaction at durable runtime and tool-trace boundaries."""

from __future__ import annotations

import re
from typing import Any

MASK = "[REDACTED]"

_PREFIXED_SECRET = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"github_pat_[A-Za-z0-9_]{12,}|gh[pousr]_[A-Za-z0-9]{12,}|"
    r"sk-[A-Za-z0-9_-]{12,}|hf_[A-Za-z0-9]{12,}|"
    r"xox[baprs]-[A-Za-z0-9-]{12,}|AIza[A-Za-z0-9_-]{20,}"
    r")"
)
_SECRET_LABEL = r"(?:api[_-]?key|access[_-]?token|auth(?:orization)?|password|passwd|secret|token)"
_QUOTED_SECRET = re.compile(
    rf"(?is)\b({_SECRET_LABEL})([\"']?\s*[:=]\s*)([\"'])((?:\\.|(?!\3)[^\\])*)\3"
)
_ESCAPED_SECRET = re.compile(
    rf'(?i)\b({_SECRET_LABEL})(\\"\s*[:=]\s*\\")(.*?)(\\")'
)
_ASSIGNMENT_SECRET = re.compile(
    rf"(?i)\b({_SECRET_LABEL})"
    r"([\"']?\s*[:=]\s*[\"']?)(?:(?:Bearer|Basic)\s+)?([^\s,;&\"']+)"
)
# Header pairs are commonly rendered as tuples instead of key:value mappings.
# The explicit Authorization label establishes sensitivity even for short keys.
_TUPLE_AUTH = re.compile(
    r"(?is)([\"']authorization[\"']\s*,\s*)([\"'])((?:\\.|(?!\2)[^\\])*)\2"
)
_ESCAPED_TUPLE_AUTH = re.compile(
    r'(?is)(\\"authorization\\"\s*,\s*\\")((?:\\\\.|(?!\\").)*)(\\")'
)
# Explicit schemes with token-shaped values; do not mask prose such as
# "Bearer authentication required". Labelled headers are handled separately.
_AUTH_SCHEME = re.compile(
    r"(?i)\b(Bearer|Basic)([ \t]+)"
    r"((?=[A-Za-z0-9._~+/-]*[0-9._~+/-])[A-Za-z0-9._~+/-]{8,}=*|[A-Za-z]{20,}=*)"
)
_URL_USERINFO = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/?#\s]+@")
_SECRET_KEY = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|auth(?:orization)?|cookie|"
    r"credential|password|passwd|secret|token)"
)


def redact_text(value: str) -> str:
    text = _URL_USERINFO.sub(lambda match: f"{match.group(1)}{MASK}@", str(value))
    text = _PREFIXED_SECRET.sub(MASK, text)
    text = _ESCAPED_TUPLE_AUTH.sub(lambda m: f"{m[1]}{MASK}{m[3]}", text)
    text = _TUPLE_AUTH.sub(lambda m: f"{m[1]}{m[2]}{MASK}{m[2]}", text)
    text = _AUTH_SCHEME.sub(lambda m: f"{m[1]}{m[2]}{MASK}", text)
    text = _ESCAPED_SECRET.sub(lambda m: f"{m[1]}{m[2]}{MASK}{m[4]}", text)
    text = _QUOTED_SECRET.sub(lambda m: f"{m[1]}{m[2]}{m[3]}{MASK}{m[3]}", text)
    return _ASSIGNMENT_SECRET.sub(lambda match: f"{match.group(1)}{match.group(2)}{MASK}", text)


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            key: MASK if _SECRET_KEY.search(str(key)) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value


__all__ = ["MASK", "redact_text", "redact_value"]
