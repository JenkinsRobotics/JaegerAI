"""Attach the windowed app to a live ``jaeger bridge`` instead of booting twice.

ARES (and ``jaeger bridge``) hold the instance lock and listen on
``run/bridge.sock``. The windowed ``jaeger`` command used to call
``boot_for_tui``, fail the flock, and dump a traceback. This module is
the other half of :mod:`jaeger_ai.core.runtime.bridge_socket`: connect,
speak the v1 protocol, leave the lock alone.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any

from jaeger_ai.core.runtime import bridge_socket as bsock
from jaeger_os.contract import protocol


class AttachedBridgeRuntime:
    """AgentRuntime that proxies turns to the process holding the lock."""

    attached = True

    def __init__(self, sock: Any, rx: Any, layout: Any, ready: dict[str, Any]) -> None:
        self._sock = sock
        self._rx = rx
        self._write_lock = threading.Lock()
        self._io_lock = threading.Lock()
        self.layout = layout
        self.ready = ready
        self.client = self
        self.boot = _AttachedBoot(self, layout)
        self._events: Any = None
        self._closed = False
        self.model_name = ready.get("model")

    def start(self, *, events: Any, bus: Any) -> None:
        self._events = events
        try:
            from jaeger_ai.main import _pipeline

            _pipeline["layout"] = self.layout
            _pipeline["chassis_bus"] = bus
        except Exception:  # noqa: BLE001 — UI still works without the pipeline
            pass

    def run_turn(self, text: str, *, session_key: str) -> dict[str, Any]:
        with self._io_lock:
            self._write({"op": "send", "text": text, "session": session_key})
            for line in self._rx:
                frame = protocol.parse(line)
                if frame is None:
                    continue
                kind = frame.get("type")
                if kind == "reply":
                    return {
                        "text": frame.get("text") or "",
                        "error": frame.get("error"),
                    }
                if kind == "tool":
                    events = self._events
                    if events is not None:
                        events.tool(
                            str(frame.get("name") or ""),
                            str(frame.get("phase") or "start"),
                            elapsed_s=float(frame.get("elapsed_s") or 0.0),
                            detail=str(frame.get("detail") or ""),
                            session=session_key,
                        )
                elif kind == "state":
                    events = self._events
                    if events is not None and frame.get("busy"):
                        events.activity("status", "working", session=session_key)
                elif kind == "request":
                    self._write({
                        "op": "respond",
                        "id": str(frame.get("id") or ""),
                        "answer": "deny",
                    })
                elif kind == "fatal":
                    return {"text": "", "error": str(frame.get("error") or "bridge failed")}
            return {"text": "", "error": "bridge closed mid-turn"}

    def steer(self, text: str) -> bool:
        try:
            self._write({"op": "steer", "text": str(text or "")})
            return True
        except Exception:  # noqa: BLE001
            return False

    def context_detail(self, session: str) -> str:
        del session
        return "attached"

    def health(self) -> dict[str, Any]:
        return {
            "implementation": "jaeger-ai-attached",
            "model": self.model_name,
            "attached": True,
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._write({"op": "quit"})
        except Exception:  # noqa: BLE001
            pass
        try:
            self._rx.close()
        except Exception:  # noqa: BLE001
            pass
        bsock.close_quietly(self._sock)
        self._sock = None

    def _write(self, frame: dict[str, Any]) -> None:
        raw = json.dumps(frame, ensure_ascii=False) + "\n"
        with self._write_lock:
            self._rx.write(raw)
            self._rx.flush()


class _AttachedBoot:
    def __init__(self, runtime: AttachedBridgeRuntime, layout: Any) -> None:
        self.client = runtime
        self.layout = layout

    def cleanup(self) -> None:
        self.client.close()


def try_attach_runtime(*, instance_name: str | None = None) -> AttachedBridgeRuntime | None:
    """Connect to a live instance socket, or return None if nobody is listening."""
    from jaeger_ai.core.instance.instance import (
        InstanceLayout,
        default_instance_name,
        resolve_instance_dir,
    )

    name = instance_name or default_instance_name()
    try:
        layout = InstanceLayout(resolve_instance_dir(name))
    except Exception:  # noqa: BLE001
        return None
    path = bsock.socket_path(layout)
    if path is None:
        return None
    sock = bsock.try_connect(path, timeout_s=1.0)
    if sock is None:
        return None
    rx = sock.makefile("rw", buffering=1, encoding="utf-8", newline="\n")
    try:
        ready = _handshake(rx)
    except Exception:
        try:
            rx.close()
        except Exception:  # noqa: BLE001
            pass
        bsock.close_quietly(sock)
        return None
    holder = _lock_holder(layout)
    where = f"pid {holder}" if holder else str(path)
    print(
        f"[jaeger] attaching to the running {layout.root.name} agent ({where}) "
        "— sharing the brain already held by ARES/jaeger bridge.",
        file=sys.stderr,
        flush=True,
    )
    return AttachedBridgeRuntime(sock, rx, layout, ready)


def _handshake(rx: Any) -> dict[str, Any]:
    for line in rx:
        frame = protocol.parse(line)
        if frame is None:
            continue
        if frame.get("type") == "ready":
            return {
                "instance": frame.get("instance"),
                "model": frame.get("model"),
            }
        if frame.get("type") == "fatal":
            raise RuntimeError(str(frame.get("error") or "attach handshake failed"))
    raise RuntimeError("bridge closed before ready")


def _lock_holder(layout: Any) -> str | None:
    path = getattr(layout, "lock_path", None)
    if not isinstance(path, Path):
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text.splitlines()[0].strip() if text else None


__all__ = ["AttachedBridgeRuntime", "try_attach_runtime"]
