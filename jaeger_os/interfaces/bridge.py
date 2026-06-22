"""Headless NDJSON stdio bridge — the agent pipeline behind the native app.

The PySide6 windowed app talks to the agent *in-process* over the chassis
bus.  The Swift app is a separate process, so it spawns ``jaeger bridge``
and exchanges newline-delimited JSON over stdin/stdout — the same turn,
one hop out of process.  No socket, no port, no daemon: the bridge owns
one ``boot_for_tui`` agent and runs turns through ``run_for_voice``,
exactly like the Rich TUI, but with JSON I/O instead of a console.

Protocol — one JSON object per line:

  bridge → client (stdout):
    {"type": "ready", "instance": <str>, "model": <str|null>}
    {"type": "state", "busy": <bool>}            # brackets each turn
    {"type": "tool",  "name": <str>, "phase": <start|done|error>, "elapsed_s": <float>}
    {"type": "reply", "text": <str>, "error": <str|null>}
    {"type": "fatal", "error": <str>}            # boot failed; bridge exits

  client → bridge (stdin):
    {"text": <str>}                              # one user turn
    {"op": "quit"}                               # graceful stop (EOF also works)

stdout carries ONLY protocol JSON — model-boot logs, llama.cpp chatter,
and any stray ``print`` are forced to stderr so they can't corrupt the
stream.  Run via ``jaeger bridge`` (the shim picks the .venv interpreter)
or ``python -m jaeger_os.interfaces.bridge [instance_name]``.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO


def _emit(out: TextIO, obj: dict[str, Any]) -> None:
    """Write one protocol line and flush — the client reads line-by-line."""
    out.write(json.dumps(obj, ensure_ascii=False) + "\n")
    out.flush()


def _model_name(boot: Any) -> str | None:
    """Best-effort model label for the status line; None if unknown.

    The client's status bar falls back to the instance name when this is
    null, so a miss here is cosmetic, not fatal."""
    for owner, attr in (
        (getattr(boot, "client", None), "model_name"),
        (getattr(boot, "client", None), "model_path"),
        (getattr(boot, "layout", None), "model_name"),
    ):
        val = getattr(owner, attr, None)
        if isinstance(val, str) and val:
            # model_path → just the filename, not the whole path.
            return val.rsplit("/", 1)[-1]
    return None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    # The protocol stream is the REAL stdout.  Repoint sys.stdout at
    # stderr for the rest of the process so boot logs / stray prints land
    # on stderr and never corrupt the NDJSON the client is parsing.
    proto = sys.stdout
    sys.stdout = sys.stderr

    from jaeger_os.core.instance.instance import default_instance_name
    from jaeger_os.main import boot_for_tui, run_for_voice

    instance = (argv[0] if argv else None) or default_instance_name()

    try:
        boot = boot_for_tui(instance_name=instance)
    except Exception as exc:  # noqa: BLE001 — any boot failure is reported, not raised
        _emit(proto, {"type": "fatal", "error": str(exc)})
        return 1

    client = boot.client

    # Forward the agent loop's live tool activity to the client as
    # ``{"type":"tool",...}`` frames (same event the in-process windowed
    # app renders). Fires on this thread during run_for_voice, so it
    # serialises cleanly with reply frames on the one stdout stream.
    from jaeger_os import protocol

    class _ToolEmitter:
        def publish(self, event: str, **payload: object) -> None:
            if event == "tool.progress":
                _emit(proto, protocol.tool_frame(
                    str(payload.get("name", "")),
                    str(payload.get("phase", "start")),
                    float(payload.get("elapsed_s") or 0.0)))

    from jaeger_os.main import _pipeline
    _pipeline["event_bus"] = _ToolEmitter()

    # Keep the console permission provider from stealing a line off our
    # NDJSON stdin: surface the request to the client (so it's visible) and
    # fail safe to deny. Full interactive approval over the bridge needs
    # async stdin reads — a follow-on; the in-process window has it now.
    class _StdioDenyConfirm:
        def confirm(self, request: object) -> bool:
            _emit(proto, protocol.request_frame(
                "", "approval",
                (f"Allow {getattr(request, 'skill', '')}."
                 f"{getattr(request, 'operation', 'this action')}?")))
            return False

    try:
        from jaeger_os.core.safety.permissions import (
            AllowAllProvider, current_policy)
        policy = current_policy()
        if not isinstance(policy.confirmation, AllowAllProvider):
            policy.confirmation = _StdioDenyConfirm()
    except Exception:  # noqa: BLE001
        pass

    _emit(proto, protocol.ready_frame(instance, _model_name(boot)))

    try:
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(req, dict):
                continue
            if req.get("op") == "quit":
                break
            # ``{"op":"send","text":...}`` (protocol) or legacy ``{"text":...}``.
            text = (req.get("text") or "").strip()
            session = req.get("session") or "desktop-app"
            if not text:
                continue

            _emit(proto, protocol.state_frame(True, session))
            try:
                result = run_for_voice(client, text, session_key=session)
                _emit(proto, protocol.reply_frame(
                    result.get("text") or "", result.get("error"), session))
            except Exception as exc:  # noqa: BLE001 — a bad turn must not kill the bridge
                _emit(proto, protocol.reply_frame("", str(exc), session))
            finally:
                _emit(proto, protocol.state_frame(False, session))
    finally:
        cleanup = getattr(boot, "cleanup", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:  # noqa: BLE001 — best-effort teardown
                pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
