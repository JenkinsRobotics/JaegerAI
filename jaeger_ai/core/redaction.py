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
_ASSIGNMENT_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|auth(?:orization)?|password|passwd|secret|token)"
    r"(\s*[:=]\s*)(?:Bearer\s+)?([^\s,;]+)"
)
_SECRET_KEY = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|auth(?:orization)?|cookie|"
    r"credential|password|passwd|secret|token)"
)


def redact_text(value: str) -> str:
    text = _PREFIXED_SECRET.sub(MASK, str(value))
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
