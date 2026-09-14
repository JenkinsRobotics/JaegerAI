"""Safe, bounded summaries for operator-facing agent telemetry."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_PATH_KEYS = ("artifact", "file", "filename", "output_path", "path", "saved")
_SECRET_KEYS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)


def _mask_secret_fields(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: (
                "***"
                if any(hint in str(key).lower() for hint in _SECRET_KEYS)
                else _mask_secret_fields(child)
            )
            for key, child in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_mask_secret_fields(child) for child in value]
    return value


def safe_preview(value: Any, *, limit: int = 800) -> str:
    """Return a redacted, single-line preview suitable for a live UI."""
    value = _mask_secret_fields(value)

    def redact_text(text: Any) -> Any:
        return text

    try:
        from jaeger_os.core.safety.redact import redact_obj, redact_text

        value = redact_obj(value)
    except Exception:  # noqa: BLE001 - observability must never break a tool call
        pass
    if isinstance(value, str):
        rendered = value
    else:
        try:
            rendered = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            rendered = repr(value)
    # A structured key such as ``api_key`` becomes recognizable only after
    # serialization, so run the text pass as well as the recursive value pass.
    rendered = str(redact_text(rendered))
    rendered = " ".join(rendered.split())
    if len(rendered) <= limit:
        return rendered
    return rendered[: max(0, limit - 1)] + "…"


def artifact_paths(value: Any, *, limit: int = 12) -> tuple[str, ...]:
    """Extract path-like values explicitly identified as outputs/artifacts."""
    found: list[str] = []

    def add(candidate: Any) -> None:
        text = str(candidate).strip()
        if (
            not text
            or text.startswith(("http://", "https://", "data:"))
            or "\n" in text
            or len(text) > 500
        ):
            return
        if text not in found:
            found.append(text)

    def walk(item: Any, parent_key: str = "") -> None:
        if len(found) >= limit:
            return
        if isinstance(item, Mapping):
            for key, child in item.items():
                label = str(key).lower()
                if any(hint in label for hint in _PATH_KEYS):
                    if isinstance(child, (str, Path)):
                        add(child)
                    elif isinstance(child, Sequence) and not isinstance(child, (str, bytes)):
                        for candidate in child:
                            if isinstance(candidate, (str, Path)):
                                add(candidate)
                walk(child, label)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            for child in item:
                walk(child, parent_key)

    walk(value)
    return tuple(found[:limit])


__all__ = ["artifact_paths", "safe_preview"]
