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


def _active_character(boot: Any) -> tuple[str | None, str | None]:
    """The active character's (display name, profile-icon path) — for the native
    client's tray/header. Best-effort; a miss is cosmetic."""
    try:
        from jaeger_os.personality.character import active_character
        root = getattr(getattr(boot, "layout", None), "root", None)
        if root is not None:
            c = active_character(root)
            if c is not None:
                icon = c.icon_path()
                return c.name, (str(icon) if icon else None)
    except Exception:  # noqa: BLE001
        pass
    return None, None


_LAYERS = ("hexaco", "special", "expression", "domains")


def _instance_root(boot: Any) -> Any:
    return getattr(getattr(boot, "layout", None), "root", None)


def _char_summary(c: Any, active_id: Any, bound_id: Any) -> dict[str, Any]:
    from jaeger_os.personality.character import layer_items
    stats: list[dict[str, Any]] = []
    for layer in _LAYERS:
        sub = getattr(c.personality, layer, None)
        if sub is not None:
            stats += [{"key": k, "val": float(v)} for k, v in layer_items(sub)]
    icon = c.icon_path()
    return {"id": c.id, "name": c.name, "role": c.role, "level": c.level,
            "revision": c.revision, "icon": str(icon) if icon else None,
            "active": c.id == active_id, "bound": c.id == bound_id, "stats": stats}


def _char_detail(c: Any) -> dict[str, Any]:
    from jaeger_os.personality.character import layer_items
    traits: dict[str, dict[str, float]] = {}
    for layer in _LAYERS:
        sub = getattr(c.personality, layer, None)
        if sub is not None:
            traits[layer] = {k: round(float(v), 3) for k, v in layer_items(sub)}
    icon = c.icon_path()
    return {"id": c.id, "name": c.name, "role": c.role, "level": c.level,
            "voice_tone": c.voice_tone, "voice_id": c.voice_id,
            "soul": c.soul, "backstory": c.backstory,
            "custom_instructions": getattr(c.personality, "custom_instructions", ""),
            "icon": str(icon) if icon else None, "traits": traits}


def _query(what: str, args: dict[str, Any], boot: Any) -> Any:
    """Read-only accessors for the native settings HUD — the same data the
    PySide6 window reads, over the pipe."""
    from jaeger_os.personality.character import (
        active_character, active_character_id, bound_character_id, list_characters,
    )
    root = _instance_root(boot)
    lay = getattr(boot, "layout", None)
    if what == "characters":
        active_id = active_character_id(root) if root else None
        bound_id = bound_character_id(root) if root else None
        return [_char_summary(c, active_id, bound_id) for c in list_characters()]
    if what == "character":
        cid = args.get("id")
        c = next((x for x in list_characters() if x.id == cid), None) if cid else None
        if c is None and root is not None:
            c = active_character(root)
        return _char_detail(c) if c is not None else None
    if what == "config":
        from jaeger_os.core.instance.schemas import Config, Identity, load_yaml
        cfg = load_yaml(lay.config_path, Config)
        ident = load_yaml(lay.identity_path, Identity)
        return {"name": ident.name, "role": ident.role,
                "default_mode": cfg.interaction.default_mode, "ui": cfg.interaction.ui,
                "voice_enabled": cfg.voice.enabled, "speak_replies": cfg.voice.speak_replies,
                "show_latency": cfg.display.show_latency,
                "show_tool_activity": cfg.display.show_tool_activity,
                "idle_minutes": cfg.deep_think.auto_idle_minutes,
                "allow_lazy_installs": cfg.security.allow_lazy_installs,
                "permission_mode": cfg.permissions.mode}
    if what == "permissions":
        from jaeger_os.core.instance.schemas import Config, load_yaml
        from jaeger_os.core.safety.permissions import PermissionGrants
        cfg = load_yaml(lay.config_path, Config)
        return {"mode": cfg.permissions.mode,
                "granted": sorted(PermissionGrants.load(root).persistent)}
    return None


def _command(cmd: str, args: dict[str, Any], boot: Any) -> tuple[bool, str | None]:
    """Mutations for the settings HUD — each forwards to a tested function."""
    root = _instance_root(boot)
    lay = getattr(boot, "layout", None)
    try:
        import jaeger_os.personality.character as ch
        if cmd == "select_character":
            ch.set_active_character(root, args["id"]); return True, None
        if cmd == "make_default":
            ch.bind_character(root, args["id"]); return True, None
        if cmd == "save_profile":
            c = ch.active_character(root)
            ch.save_character_profile(
                c.root, role=args.get("role"), voice_tone=args.get("voice_tone"),
                voice_id=args.get("voice_id"), soul=args.get("soul"),
                backstory=args.get("backstory"),
                custom_instructions=args.get("custom_instructions"))
            return True, None
        if cmd == "save_traits":
            c = ch.active_character(root)
            ch.save_character_traits(c.root, args.get("traits") or {}); return True, None
        if cmd == "save_config":
            from jaeger_os.core.instance.schemas import Config, dump_yaml, load_yaml
            cfg = load_yaml(lay.config_path, Config)
            _apply_config(cfg, args)
            dump_yaml(lay.config_path, Config.model_validate(cfg.model_dump()))
            return True, None
        if cmd == "revoke_permission":
            from jaeger_os.core.safety.permissions import PermissionGrants
            PermissionGrants.load(root).revoke(args["skill"]); return True, None
        return False, f"unknown command: {cmd}"
    except Exception as exc:  # noqa: BLE001 — a bad command reports, never crashes the bridge
        return False, str(exc)


def _apply_config(cfg: Any, m: dict[str, Any]) -> None:
    fields = {
        "default_mode": ("interaction", "default_mode"), "ui": ("interaction", "ui"),
        "voice_enabled": ("voice", "enabled"), "speak_replies": ("voice", "speak_replies"),
        "show_latency": ("display", "show_latency"),
        "show_tool_activity": ("display", "show_tool_activity"),
        "idle_minutes": ("deep_think", "auto_idle_minutes"),
        "allow_lazy_installs": ("security", "allow_lazy_installs"),
        "permission_mode": ("permissions", "mode"),
    }
    for key, (section, attr) in fields.items():
        if key in m:
            setattr(getattr(cfg, section), attr, m[key])


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
    from jaeger_os.interfaces import protocol

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

    _char_name, _char_icon = _active_character(boot)
    _emit(proto, protocol.ready_frame(instance, _model_name(boot),
                                      _char_name, _char_icon))

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
            if req.get("op") == "query":
                try:
                    data = _query(req.get("what") or "", req.get("args") or {}, boot)
                    _emit(proto, protocol.result_frame(req.get("id"), data=data))
                except Exception as exc:  # noqa: BLE001
                    _emit(proto, protocol.result_frame(req.get("id"), ok=False, error=str(exc)))
                continue
            if req.get("op") == "command":
                ok, err = _command(req.get("cmd") or "", req.get("args") or {}, boot)
                _emit(proto, protocol.result_frame(req.get("id"), ok=ok, error=err))
                continue
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
