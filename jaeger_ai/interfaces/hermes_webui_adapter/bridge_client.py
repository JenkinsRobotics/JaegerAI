"""Request client for the live Jaeger bridge socket."""

from __future__ import annotations

import json
import socket
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jaeger_os.contract import protocol

from jaeger_ai.core.instance.instance import (
    InstanceLayout,
    default_instance_name,
    resolve_instance_dir,
)
from jaeger_ai.core.runtime import bridge_socket


class HermesWebUIAdapterBridgeError(RuntimeError):
    pass


class BridgeClient:
    """Keep Jaeger as runtime owner; the WebUI is only a protocol client."""

    def __init__(self, instance: str | None = None) -> None:
        self.instance = instance or default_instance_name()
        self.layout = InstanceLayout(resolve_instance_dir(self.instance))

    @property
    def socket_path(self) -> Path:
        path = bridge_socket.socket_path(self.layout)
        if path is None:
            raise HermesWebUIAdapterBridgeError("Jaeger instance has no bridge socket path")
        return path

    def health(self) -> dict[str, Any]:
        try:
            with self._connection() as (_sock, rx):
                ready = self._ready(rx)
            return {"ok": True, "instance": self.instance, "ready": ready}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "instance": self.instance, "error": str(exc)}

    def query(self, what: str, args: dict[str, Any] | None = None) -> Any:
        return self._request({"op": "query", "what": what, "args": args or {}})

    def command(self, command: str, args: dict[str, Any] | None = None) -> Any:
        return self._request({"op": "command", "cmd": command, "args": args or {}})

    def control(self, operation: str, **payload: Any) -> None:
        """Send a fire-and-forget bridge control such as cancel or steer."""
        if operation not in {"cancel", "steer"}:
            raise ValueError(f"unsupported bridge control: {operation}")
        with self._connection() as (_sock, rx):
            self._ready(rx)
            self._write(rx, {"op": operation, **payload})

    def turn(self, text: str, session: str,
             on_event: Callable[[dict[str, Any]], None] | None = None,
             on_request: Callable[[dict[str, Any]], str] | None = None) -> dict[str, Any]:
        with self._connection() as (_sock, rx):
            self._ready(rx)
            self._write(rx, {"op": "send", "text": text, "session": session})
            for line in rx:
                frame = protocol.parse(line)
                if frame is None:
                    continue
                kind = frame.get("type")
                if kind == "reply":
                    return {"text": frame.get("text") or "", "error": frame.get("error")}
                if kind == "request":
                    answer = on_request(frame) if on_request is not None else "deny"
                    self._write(rx, {"op": "respond", "id": str(frame.get("id") or ""), "answer": answer or "deny"})
                    frame = {**frame, "answer": answer or "deny", "policy": "interactive-web" if on_request else "web-default-deny"}
                if on_event is not None and kind in {"delta", "reasoning", "tool", "state", "queued", "request"}:
                    on_event(frame)
                if kind == "fatal":
                    raise HermesWebUIAdapterBridgeError(str(frame.get("error") or "bridge failed"))
        raise HermesWebUIAdapterBridgeError("bridge closed before replying")

    def _request(self, payload: dict[str, Any]) -> Any:
        request_id = uuid.uuid4().hex
        with self._connection() as (_sock, rx):
            self._ready(rx)
            self._write(rx, {**payload, "id": request_id})
            for line in rx:
                frame = protocol.parse(line)
                if frame is None:
                    continue
                if frame.get("type") == "result" and str(frame.get("id") or "") == request_id:
                    if frame.get("ok", True) is False:
                        raise HermesWebUIAdapterBridgeError(
                            str(frame.get("error") or "bridge request failed")
                        )
                    return frame.get("data")
                if frame.get("type") == "fatal":
                    raise HermesWebUIAdapterBridgeError(str(frame.get("error") or "bridge failed"))
        raise HermesWebUIAdapterBridgeError("bridge closed before returning a result")

    def _connection(self):
        sock = bridge_socket.try_connect(self.socket_path, timeout_s=2.0)
        if sock is None:
            raise HermesWebUIAdapterBridgeError(
                f"Jaeger bridge is not listening at {self.socket_path}"
            )
        return _SocketConnection(sock)

    @staticmethod
    def _ready(rx: Any) -> dict[str, Any]:
        for line in rx:
            frame = protocol.parse(line)
            if frame is None:
                continue
            if frame.get("type") == "ready":
                return frame
            if frame.get("type") == "fatal":
                raise HermesWebUIAdapterBridgeError(
                    str(frame.get("error") or "bridge handshake failed")
                )
        raise HermesWebUIAdapterBridgeError("bridge closed during handshake")

    @staticmethod
    def _write(rx: Any, frame: dict[str, Any]) -> None:
        rx.write(json.dumps(frame, ensure_ascii=False) + "\n")
        rx.flush()


class _SocketConnection:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.rx: Any = None

    def __enter__(self):
        self.rx = self.sock.makefile("rw", buffering=1, encoding="utf-8", newline="\n")
        return self.sock, self.rx

    def __exit__(self, *_exc: object) -> None:
        if self.rx is not None:
            try:
                self.rx.close()
            except OSError:
                pass
        bridge_socket.close_quietly(self.sock)
