"""Persistent Global Stop, using the caller identities jaegerd already assigned.

Engaging it is the ``stop`` scope. Releasing it is an authenticated owner
action (``admin`` scope and an owner caller). MCP, A2A, OpenClaw, and a
forged role cannot release it. A corrupt latch stays engaged.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from jaeger_ai.core.gateway.caller_auth import CallerSpec

OWNER_RELEASE_CALLERS = frozenset({"menubar", "cli", "webui", "ide"})
_ENV = "JAEGER_GLOBAL_STOP_PATH"


class GlobalStopError(RuntimeError):
    pass


@dataclass(frozen=True)
class StopState:
    engaged: bool
    reason: str = ""
    engaged_by: str = ""
    unconfirmed: tuple[str, ...] = ()


class GlobalStop:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def load(cls) -> GlobalStop:
        raw = os.environ.get(_ENV, "").strip()
        if raw:
            return cls(Path(raw).expanduser())
        from jaeger_ai.core.instance.instance import operator_state_root
        return cls(operator_state_root() / "control" / "global-stop.json")

    def read(self) -> StopState:
        if not self.path.exists():
            return StopState(False)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GlobalStopError("global stop latch is unreadable") from exc
        if not isinstance(raw, dict) or "engaged" not in raw:
            raise GlobalStopError("global stop latch is malformed")
        return StopState(
            engaged=bool(raw.get("engaged")),
            reason=str(raw.get("reason") or ""),
            engaged_by=str(raw.get("engaged_by") or ""),
            unconfirmed=tuple(str(item) for item in (raw.get("unconfirmed") or [])),
        )

    def engaged(self) -> bool:
        try:
            return self.read().engaged
        except GlobalStopError:
            return True

    def engage(self, caller: str, *, reason: str, unconfirmed: list[str] | None = None) -> StopState:
        state = StopState(
            True,
            reason=(reason or "stop").strip() or "stop",
            engaged_by=caller,
            unconfirmed=tuple(unconfirmed or ()),
        )
        self._write(state)
        return state

    def release(self, spec: CallerSpec) -> StopState:
        if not release_allowed(spec):
            raise GlobalStopError("only an authenticated owner can release global stop")
        state = StopState(False)
        self._write(state)
        return state

    def _write(self, state: StopState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "engaged": state.engaged,
            "reason": state.reason,
            "engaged_by": state.engaged_by,
            "unconfirmed": list(state.unconfirmed),
        }
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)
        os.chmod(self.path, 0o600)


def release_allowed(spec: CallerSpec) -> bool:
    """Owner callers only. Scope is necessary and not sufficient."""
    return spec.name in OWNER_RELEASE_CALLERS and "admin" in spec.scopes


def allowed_while_stopped(method: str, route: str | None, spec: CallerSpec) -> bool:
    """The only requests that may proceed while Stop is latched or the owner is gone."""
    method = (method or "").upper()
    route = route or ""
    if method == "GET" and route == "/v1/stop":
        return "read" in spec.scopes
    if method == "POST" and route == "/v1/stop":
        return "stop" in spec.scopes or "admin" in spec.scopes
    if method == "POST" and route == "/v1/stop/release":
        return release_allowed(spec)
    return False

