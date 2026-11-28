"""JP01 wire protocols promoted from JROS (`jaeger_os/hardware/protocol.py`)."""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WireEvent:
    kind: str
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class Protocol(abc.ABC):
    @abc.abstractmethod
    def encode(self, command: Any) -> bytes: ...

    @abc.abstractmethod
    def feed(self, raw: bytes) -> list[WireEvent]: ...


class AsciiBracketProtocol(Protocol):
    """JP01 serial/ZMQ bracket command dialect (`MJ[90,100,10]\\n`, `FN[ffaa...]\\n`)."""

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
            raise TypeError(f"AsciiBracketProtocol cannot encode {type(command).__name__}")
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
    """Newline-delimited JSON protocol for auxiliary controllers."""

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
                events.append(
                    WireEvent(kind="json", text=text, data=data if isinstance(data, dict) else {"value": data})
                )
            except ValueError:
                events.append(WireEvent(kind="line", text=text))
        return events


def make_protocol(name: str) -> Protocol:
    mapping = {"ascii_bracket": AsciiBracketProtocol, "json_line": JsonLineProtocol}
    if name not in mapping:
        raise ValueError(f"unknown protocol {name!r}; known: {sorted(mapping)}")
    return mapping[name]()


__all__ = ["AsciiBracketProtocol", "JsonLineProtocol", "Protocol", "WireEvent", "make_protocol"]
