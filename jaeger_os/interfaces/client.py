"""JrosClient — the reusable out-of-process client for the JROS agent.

Any non-Python (or separate-process) surface drives the agent through this
one SDK instead of re-implementing the wire handling: it spawns ``jaeger
bridge``, speaks :mod:`jaeger_os.contract.protocol`, and exposes a clean
``start`` / ``turn`` / ``close`` API. The MCP server (#3), a web backend, a
script, or a test all use it — that's the "transports, not endpoints"
payoff. The Swift app is the same client in Swift.

Synchronous, one turn at a time (one local model). Tool/state events and
mid-turn requests surface via callbacks during a turn.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Callable

from jaeger_os.contract import protocol


class JrosError(RuntimeError):
    """The bridge failed to boot, died mid-turn, or returned a fatal."""


class JrosClient:
    """Drive a JROS agent over the client protocol.

    ``command`` defaults to running the bridge in this interpreter. Pass
    ``env={"JAEGER_INSTANCE_NAME": ...}`` to pick the instance.
    """

    def __init__(self, command: list[str] | None = None,
                 env: dict | None = None, cwd: str | None = None) -> None:
        self._command = command or [sys.executable, "-m",
                                    "jaeger_os.interfaces.bridge"]
        self._env = env
        self._cwd = cwd
        self._proc: subprocess.Popen | None = None
        self.ready: dict[str, Any] | None = None

    # ── lifecycle ─────────────────────────────────────────────────
    def start(self) -> dict[str, Any]:
        """Spawn the bridge and await its ``ready`` handshake. Returns
        ``{"instance": ..., "model": ...}``. Raises :class:`JrosError`."""
        self._proc = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,        # boot/model logs → discarded
            text=True, bufsize=1, env=self._env, cwd=self._cwd,
        )
        for line in self._proc.stdout:        # type: ignore[union-attr]
            frame = protocol.parse(line)
            if frame is None:
                continue
            if frame.get("type") == "ready":
                self.ready = {"instance": frame.get("instance"),
                              "model": frame.get("model")}
                return self.ready
            if frame.get("type") == "fatal":
                raise JrosError(str(frame.get("error", "boot failed")))
        raise JrosError("bridge exited before ready")

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._write(protocol.quit_op())
            except Exception:  # noqa: BLE001
                pass
            try:
                self._proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        self._proc = None

    def __enter__(self) -> "JrosClient":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── turns ─────────────────────────────────────────────────────
    def turn(self, text: str, session: str = "", *,
             on_event: Callable[[dict], None] | None = None,
             on_request: Callable[[dict], str] | None = None) -> dict[str, Any]:
        """Run one turn; return ``{"text": ..., "error": ...}``.

        ``on_event(frame)`` fires for each tool/state frame; ``on_request``
        is called for a mid-turn prompt and must return the answer (default
        "deny")."""
        if self._proc is None:
            raise JrosError("not started")
        self._write(protocol.send_op(text, session))
        for line in self._proc.stdout:        # type: ignore[union-attr]
            frame = protocol.parse(line)
            if frame is None:
                continue
            kind = frame.get("type")
            if kind == "reply":
                return {"text": frame.get("text", ""),
                        "error": frame.get("error")}
            if kind == "request":
                answer = on_request(frame) if on_request else "deny"
                self._write(protocol.respond_op(
                    str(frame.get("id", "")), answer or "deny"))
            elif kind in ("tool", "state"):
                if on_event is not None:
                    on_event(frame)
            elif kind == "fatal":
                raise JrosError(str(frame.get("error", "bridge failed")))
        raise JrosError("bridge exited mid-turn")

    # ── internals ─────────────────────────────────────────────────
    def _write(self, frame: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(protocol.encode(frame))
        self._proc.stdin.flush()
