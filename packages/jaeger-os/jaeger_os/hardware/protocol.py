"""Wire protocols — framing + encoding, the other half of a link.

A Protocol is a separate axis from Transport: JP01's bracket commands
ride direct serial OR the ZMQ relay unchanged. ``encode`` turns a
structured command into one wire frame; ``feed`` consumes raw inbound
bytes (any chunking — partial lines are held) and yields parsed
events.
"""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WireEvent:
    """One parsed inbound frame.

    ``kind`` ∈ {"line", "telemetry", "json"} — coarse on purpose;
    package adapters interpret payloads (they know their firmware)."""
    kind: str
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class Protocol(abc.ABC):
    @abc.abstractmethod
    def encode(self, command: Any) -> bytes:
        """Structured command (or raw str) → one wire frame."""

    @abc.abstractmethod
    def feed(self, raw: bytes) -> list[WireEvent]:
        """Consume raw bytes; return zero or more complete events.
        Stateful — partial frames are buffered across calls."""


class AsciiBracketProtocol(Protocol):
    """The JP01 dialect, first-class (plan §2.5).

    Encoding:
      * raw ``str`` passes through:        ``"CN"``       → ``b"CN\\n"``
      * ``{"header": "MJ", "args": [90, 100, 10]}`` → ``b"MJ[90,100,10]\\n"``
      * ``{"header": "FN", "payload": "ffaa…"}``    → ``b"FN[ffaa…]\\n"``

    This is exactly what the three boards parse with
    ``Serial.readStringUntil('\\n')`` (`JP01-AVC01/JP01-AVC01.ino`,
    `JP01-MC01/JP01-MC01.ino`) and what
    ``JP01-CC01/devices/neopixel.py``'s builders emit.

    Inbound: lines containing "STATUS UPDATE" classify as
    ``telemetry`` (the firmware's 30 s heartbeat convention); all
    other lines are ``line`` events.
    """

    def __init__(self) -> None:
        self._buf = b""

    def encode(self, command: Any) -> bytes:
        if isinstance(command, bytes):
            line = command.decode("utf-8", "replace")
        elif isinstance(command, str):
            line = command
        elif isinstance(command, dict):
            header = str(command.get("header") or "").strip()
            if not header:
                raise ValueError("bracket command needs a 'header'")
            if "payload" in command:
                line = f"{header}[{command['payload']}]"
            elif "args" in command:
                args = ",".join(str(a) for a in (command["args"] or []))
                line = f"{header}[{args}]"
            else:
                line = header
        else:
            raise TypeError(
                f"AsciiBracketProtocol can't encode {type(command).__name__}"
            )
        return (line.strip() + "\n").encode("utf-8")

    def feed(self, raw: bytes) -> list[WireEvent]:
        self._buf += raw
        events: list[WireEvent] = []
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            text = line.decode("utf-8", "replace").strip()
            if not text:
                continue
            kind = "telemetry" if "STATUS UPDATE" in text.upper() else "line"
            events.append(WireEvent(kind=kind, text=text))
        return events


class JsonLineProtocol(Protocol):
    """Newline-delimited JSON — the VCC01 REP payload shape."""

    def __init__(self) -> None:
        self._buf = b""

    def encode(self, command: Any) -> bytes:
        if isinstance(command, str):
            return (command.strip() + "\n").encode("utf-8")
        return (json.dumps(command, ensure_ascii=False) + "\n").encode("utf-8")

    def feed(self, raw: bytes) -> list[WireEvent]:
        self._buf += raw
        events: list[WireEvent] = []
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            text = line.decode("utf-8", "replace").strip()
            if not text:
                continue
            try:
                data = json.loads(text)
                events.append(WireEvent(
                    kind="json", text=text,
                    data=data if isinstance(data, dict) else {"value": data},
                ))
            except ValueError:
                events.append(WireEvent(kind="line", text=text))
        return events


_PROTOCOLS = {
    "ascii_bracket": AsciiBracketProtocol,
    "json_line": JsonLineProtocol,
}


def make_protocol(name: str) -> Protocol:
    """Topology ``protocol:`` value → instance. Unknown names refuse
    loudly at load time."""
    try:
        return _PROTOCOLS[name]()
    except KeyError:
        raise ValueError(
            f"unknown protocol {name!r}; known: {sorted(_PROTOCOLS)}"
        ) from None


__all__ = [
    "Protocol", "WireEvent",
    "AsciiBracketProtocol", "JsonLineProtocol", "make_protocol",
]
