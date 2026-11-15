"""Sidecar: which live channel a cron fire should notify.

Schedules live in jaeger-agent's sqlite table, which has no deliver
column. Delivery is JaegerAI product state — channel + recipient per
schedule name — stored next to the board at
``<instance>/memory/cron_delivery.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_STORE = "cron_delivery.json"
CHANNELS = ("telegram", "discord", "imessage")


def _path(layout: Any) -> Path | None:
    mem = getattr(layout, "memory_dir", None)
    if mem is not None:
        return Path(mem) / _STORE
    root = getattr(layout, "root", None)
    if root is None:
        return None
    return Path(str(root)) / "memory" / _STORE


def _load(layout: Any) -> dict[str, Any]:
    path = _path(layout)
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _save(layout: Any, data: dict[str, Any]) -> None:
    path = _path(layout)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def remember(layout: Any, name: str, *, channel: str, recipient: str) -> dict[str, str]:
    channel_c = (channel or "").strip().lower()
    recipient_c = (recipient or "").strip()
    name_c = (name or "").strip()
    if not name_c or channel_c not in CHANNELS or not recipient_c:
        raise ValueError(
            f"deliver needs channel in {CHANNELS} and a recipient"
        )
    data = _load(layout)
    row = {"channel": channel_c, "recipient": recipient_c}
    data[name_c] = row
    _save(layout, data)
    return row


def lookup(layout: Any, name: str) -> dict[str, str] | None:
    row = _load(layout).get((name or "").strip())
    if not isinstance(row, dict):
        return None
    channel = str(row.get("channel") or "").strip().lower()
    recipient = str(row.get("recipient") or "").strip()
    if channel not in CHANNELS or not recipient:
        return None
    return {"channel": channel, "recipient": recipient}


def forget(layout: Any, name: str) -> bool:
    data = _load(layout)
    if (name or "").strip() not in data:
        return False
    data.pop((name or "").strip(), None)
    _save(layout, data)
    return True


def deliver_text(layout: Any, name: str, text: str) -> dict[str, Any] | None:
    """Send ``text`` on the schedule's channel, if one is configured.

    Returns the send_message result, or None when this schedule has no
    delivery target. Fail-open: a missing bridge is a result dict, not
    an exception.
    """
    target = lookup(layout, name)
    body = (text or "").strip()
    if not body:
        return {"sent": False, "error": "empty body"}
    if _is_quiet(body):
        # Heartbeat-style "nothing to report" replies stay in the app.
        return None
    if target is None:
        # Default: the owner's phone channels (Telegram / iMessage self-chat)
        # through the channels relay outbox, deduped per schedule occurrence.
        return _relay_enqueue(name, body)
    try:
        from jaeger_agent.tools.messaging import send_message
        sent = send_message(
            channel=target["channel"],
            recipient=target["recipient"],
            text=body,
        )
    except Exception as exc:  # noqa: BLE001
        sent = {"sent": False, "error": f"{type(exc).__name__}: {exc}"}
    if not sent.get("sent") and not sent.get("execution_unknown") and target["channel"] in ("telegram", "imessage"):
        # No in-process bridge: the channels relay owns these transports.
        return _relay_enqueue(name, body, channels=[target["channel"]])
    return sent


_QUIET = ("HEARTBEAT_OK", "NO_REPLY", "NOTHING_TO_REPORT")


def _is_quiet(body: str) -> bool:
    head = body.strip().strip("`*_ .").upper()
    return any(head == q or head.startswith(q + " ") or head.endswith(q) for q in _QUIET)


def _relay_enqueue(name: str, body: str, channels: list[str] | None = None) -> dict[str, Any]:
    try:
        from jaeger_ai.features.channels.relay.outbox import enqueue
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "error": f"channels relay unavailable: {exc}"}
    import hashlib
    import time as _time
    key = f"schedule:{name}:{_time.strftime('%Y-%m-%dT%H')}:{hashlib.sha256(body.encode()).hexdigest()[:12]}"
    res = enqueue(body, kind="schedule", title=f"⏰ {name}", dedupe_key=key, channels=channels)
    return {"sent": bool(res.get("queued")), "queued": True, **res}


__all__ = [
    "CHANNELS",
    "deliver_text",
    "forget",
    "lookup",
    "remember",
]
