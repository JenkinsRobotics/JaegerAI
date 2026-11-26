"""Ephemeral Statusbar context injector (adapted from AG2 ``middleware/statusbar.py``, Apache-2.0).

Appends fresh runtime awareness (32 GB RAM headroom, active priority mode, active
business/Minecraft goals, workspace info) to outbound model requests WITHOUT
persisting ephemeral status noise into stored conversation transcripts.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

StatusProvider = Callable[[], Mapping[str, Any]]

EPHEMERAL_MARKER = "[JAEGER_EPHEMERAL_STATUS]"


def build_ephemeral_status_message(providers: Sequence[StatusProvider]) -> dict[str, str] | None:
    lines: list[str] = []
    for fn in providers:
        try:
            data = fn() or {}
        except Exception:  # noqa: BLE001
            continue
        for k, v in data.items():
            if v is not None and v != "":
                lines.append(f"- {k}: {v}")
    if not lines:
        return None
    return {
        "role": "system",
        "content": f"{EPHEMERAL_MARKER}\nCurrent live runtime context (ephemeral, not saved to history):\n" + "\n".join(lines),
    }


def inject_ephemeral_status(
    messages: Sequence[Mapping[str, Any]],
    providers: Sequence[StatusProvider],
) -> list[dict[str, Any]]:
    """Return a copy of ``messages`` with fresh ephemeral status injected (stripping any prior status)."""
    cleaned = [
        dict(m)
        for m in messages
        if not (m.get("role") == "system" and str(m.get("content") or "").startswith(EPHEMERAL_MARKER))
    ]
    status_msg = build_ephemeral_status_message(providers)
    if status_msg is not None:
        cleaned.append(status_msg)
    return cleaned


__all__ = [
    "EPHEMERAL_MARKER",
    "StatusProvider",
    "build_ephemeral_status_message",
    "inject_ephemeral_status",
]
