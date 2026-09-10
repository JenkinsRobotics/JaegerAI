"""Bounded JSONL and structured-content helpers shared by import sources."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

MAX_LINE_BYTES = 2 * 1024 * 1024
MAX_MESSAGE_CHARS = 100_000


def jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("rb") as stream:
        for raw in stream:
            if len(raw) > MAX_LINE_BYTES:
                continue
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                yield value


def content_text(value: Any) -> str:
    if isinstance(value, str):
        return value[:MAX_MESSAGE_CHARS]
    if isinstance(value, list):
        parts = [content_text(item) for item in value]
        return "\n".join(part for part in parts if part)[:MAX_MESSAGE_CHARS]
    if isinstance(value, dict):
        kind = str(value.get("type") or "")
        if kind in {
            "text",
            "input_text",
            "output_text",
            "tool_result",
            "message",
        }:
            for key in ("text", "content", "output"):
                if key in value:
                    return content_text(value[key])
    return ""


def timestamp(value: Any, fallback: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            from datetime import datetime

            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            pass
    return fallback
