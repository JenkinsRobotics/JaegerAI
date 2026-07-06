"""Headless NDJSON stdio bridge — the agent pipeline behind the native app.

The Swift shell spawns ``jaeger bridge`` and exchanges newline-delimited
JSON over stdin/stdout — the same agent turn the TUI runs, one hop out of
process.  Protocol v1 lives in ``protocol.py`` (the single wire contract)
with ``protocol_v1_fixtures.json`` as the cross-language test fixtures.

Phase-1 hardening (SWIFT_APP_ARCHITECTURE_PLAN.md, approved 2026-07-04):

  * FAST READY — ``ready`` is emitted the moment the TRANSPORT is usable
    (layout resolved; queries/commands work immediately).  The model boots
    on a background thread; ``agent_state`` frames stream
    ``booting → ready | failed`` so the shell separates "UI usable" from
    "agent warm".  Chat turns queue and BLOCK until boot completes, so
    older clients (JrosClient) keep their semantics.
  * WORKER-THREAD TURNS — the stdin loop never blocks on a turn, so
    ``respond`` (permission answers) and ``quit`` stay processable mid-turn.
  * INTERACTIVE PERMISSIONS — approval requests surface as ``request``
    frames; ``{"op":"respond","id":…,"answer":…}`` resolves them (timeout
    ⇒ deny, fail-safe).
  * CLEAN-EXIT MARKER — ``bye`` is emitted before exit, and the process
    leaves through ``os._exit`` past the ggml Metal teardown abort (F1),
    so the client can trust "bye seen = orderly, no bye = crash".

stdout carries ONLY protocol JSON — model-boot logs, llama.cpp chatter,
and any stray ``print`` are forced to stderr so they can't corrupt the
stream.  Run via ``jaeger bridge`` (the shim picks the .venv interpreter)
or ``python -m jaeger_os.interfaces.bridge [instance_name]``.
"""

from __future__ import annotations

import json
import os
import queue as _queue
import sys
import threading
from typing import Any, TextIO

_emit_lock = threading.Lock()


def _emit(out: TextIO, obj: dict[str, Any]) -> None:
    """Write one protocol line and flush — the client reads line-by-line.
    Locked: the turn worker and the stdin thread share one stream."""
    with _emit_lock:
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


def _agent_name(boot: Any) -> str | None:
    """The AGENT's own name (identity.yaml — the unique robot the operator
    named), NEVER the character. Every branded surface leads with this."""
    try:
        from jaeger_os.core.instance.schemas import Identity, load_yaml
        lay = getattr(boot, "layout", None)
        return (load_yaml(lay.identity_path, Identity).name or "").strip() or None
    except Exception:  # noqa: BLE001 — cosmetic; surfaces fall back to character
        return None


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
    card = c.card_path()
    return {"id": c.id, "name": c.name, "role": c.role, "level": c.level,
            "revision": c.revision, "icon": str(icon) if icon else None,
            "card": str(card) if card else None,
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
    if what == "identity":
        # The agent's live identity for tray/header/orb branding — cheap
        # enough to re-ask after a character switch (the client refreshes
        # this instead of waiting for the next agent_state frame).
        # v1 additive ``agent_name``: the AGENT's name (identity.yaml —
        # the unique robot named at instance creation). ``character`` is
        # the persona being played; surfaces lead with agent_name and show
        # the character as secondary flavor ("Ted · playing HAL 9000").
        name, icon = _active_character(boot)
        return {"agent_name": _agent_name(boot), "character": name, "icon": icon,
                "model": _model_name(boot)}
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
                "speech_engine": cfg.voice.speech_engine,
                "show_latency": cfg.display.show_latency,
                "show_tool_activity": cfg.display.show_tool_activity,
                "activity_trace": cfg.display.activity_trace,
                "turn_separators": cfg.display.turn_separators,
                "idle_minutes": cfg.deep_think.auto_idle_minutes,
                "allow_lazy_installs": cfg.security.allow_lazy_installs,
                "permission_mode": cfg.permissions.mode,
                # v1 additive — the two context-window knobs (tokens).
                # model_ctx sizes the WORKER lane (agent loop KV);
                # model_aux_ctx sizes the AUX lane (persona filter /
                # finalizer / reflection side calls, 0 = disabled).
                # Both apply on agent restart, not live.
                "model_ctx": cfg.model.ctx,
                "model_aux_ctx": cfg.model.aux_ctx}
    if what == "settings_catalog":
        # The schema-derived settings surface — the SAME catalog `jaeger
        # settings` drives. Grouped {group: [descriptor, ...]}; the native
        # app renders each descriptor by type (bool→Toggle, enum→Picker,
        # int/float→field, str→field). No hand-enumerated field list on
        # either side — a new setting is one annotated Field in schemas.py.
        from jaeger_os.core.settings.catalog import catalog as _catalog
        return _catalog(lay, advanced=bool(args.get("advanced", True)),
                        group=args.get("group"))
    if what == "permissions":
        from jaeger_os.core.instance.schemas import Config, load_yaml
        from jaeger_os.core.safety.permissions import PermissionGrants
        cfg = load_yaml(lay.config_path, Config)
        return {"mode": cfg.permissions.mode,
                "granted": sorted(PermissionGrants.load(root).persistent)}
    if what == "instance_exists":
        # v1 additive: first-run probe — does the resolved instance
        # exist on disk? Works pre-boot (fast-ready) and pre-instance.
        return {"exists": bool(lay is not None and lay.exists()),
                "root": str(lay.root) if lay is not None else None}
    if what == "setup_defaults":
        # v1 additive: host tier + recommended models + voices for the
        # native onboarding — the same data the CLI wizard prints.
        from jaeger_os.core.instance.setup_wizard import setup_defaults
        return setup_defaults()
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
        if cmd == "speak":
            # The agent's REAL voice for the native app's speaker button:
            # synthesize via the Python-side Kokoro node with the ACTIVE
            # character's configured voice (agent.tools.speak resolves it).
            # Fire-and-forget on a worker thread — narration can outlive the
            # client's 15 s request timeout, and the stdin loop must stay
            # free for respond/quit — so ok here means "accepted", and any
            # synth failure lands in the bridge's stderr log.
            text = str(args.get("text") or "").strip()
            if not text:
                return False, "nothing to speak"
            if getattr(boot, "client", None) is None:
                return False, "agent still booting"

            def _speak_bg() -> None:
                try:
                    from jaeger_os.agent.tools.speak import speak
                    out = speak(text=text)
                    if not out.get("spoken"):
                        print(f"[bridge] speak failed: {out.get('reason')}",
                              file=sys.stderr, flush=True)
                except Exception as exc:  # noqa: BLE001 — never crash the bridge
                    print(f"[bridge] speak crashed: {exc}",
                          file=sys.stderr, flush=True)

            threading.Thread(target=_speak_bg, name="bridge-speak",
                             daemon=True).start()
            return True, None
        return False, f"unknown command: {cmd}"
    except Exception as exc:  # noqa: BLE001 — a bad command reports, never crashes the bridge
        return False, str(exc)


def _apply_config(cfg: Any, m: dict[str, Any]) -> None:
    fields = {
        "default_mode": ("interaction", "default_mode"), "ui": ("interaction", "ui"),
        "voice_enabled": ("voice", "enabled"), "speak_replies": ("voice", "speak_replies"),
        "speech_engine": ("voice", "speech_engine"),
        "show_latency": ("display", "show_latency"),
        "show_tool_activity": ("display", "show_tool_activity"),
        "activity_trace": ("display", "activity_trace"),
        "turn_separators": ("display", "turn_separators"),
        "idle_minutes": ("deep_think", "auto_idle_minutes"),
        "allow_lazy_installs": ("security", "allow_lazy_installs"),
        "permission_mode": ("permissions", "mode"),
        # Context-window knobs (applies on restart — see ModelConfig).
        "model_ctx": ("model", "ctx"),
        "model_aux_ctx": ("model", "aux_ctx"),
    }
    for key, (section, attr) in fields.items():
        if key in m:
            setattr(getattr(cfg, section), attr, m[key])


class _Ctx:
    """Shared bridge state across the stdin thread, the boot thread, and
    the turn worker. ``layout`` is resolved cheaply up front so queries
    work pre-boot; ``boot``/``client`` land when the model finishes."""

    def __init__(self) -> None:
        self.layout: Any = None
        self.boot: Any = None
        self.client: Any = None
        self.cron: Any = None                 # CronRunner — fires scheduled prompts
        self.boot_error: str | None = None
        self.booted = threading.Event()      # set on success OR failure
        # Pending permission requests: id → (event, answer-slot). An answer
        # that arrives before the request is registered (pipelined client,
        # tests) parks in ``early`` and resolves on registration.
        self.pending: dict[str, tuple[threading.Event, list[str]]] = {}
        self.early: dict[str, str] = {}
        self.req_counter = 0


class _BridgeConfirm:
    """Interactive approval over the wire: emit a ``request`` frame, block
    (on the TURN thread — stdin stays free) until ``respond`` arrives.
    Timeout or a dead client ⇒ deny, fail-safe."""

    TIMEOUT_S = 120.0

    def __init__(self, proto: TextIO, ctx: _Ctx) -> None:
        self._proto = proto
        self._ctx = ctx

    def confirm(self, request: object) -> bool:
        from jaeger_os.interfaces import protocol
        self._ctx.req_counter += 1
        rid = f"perm{self._ctx.req_counter}"
        evt: threading.Event = threading.Event()
        slot: list[str] = []
        self._ctx.pending[rid] = (evt, slot)
        early = self._ctx.early.pop(rid, None)
        if early is not None:
            slot.append(early)
            evt.set()
        _emit(self._proto, protocol.request_frame(
            rid, "approval",
            (f"Allow {getattr(request, 'skill', '')}."
             f"{getattr(request, 'operation', 'this action')}?"),
            options=("allow", "deny")))
        try:
            if not evt.wait(self.TIMEOUT_S):
                return False
            answer = (slot[0] if slot else "").strip().lower()
            return answer in ("allow", "yes", "y", "true", "1", "approve")
        finally:
            self._ctx.pending.pop(rid, None)


def _boot_agent(proto: TextIO, ctx: _Ctx, instance: str) -> None:
    """Background boot: load the model, wire tool/permission forwarding,
    then stream the ``agent_state`` transition. Never raises."""
    from jaeger_os.interfaces import protocol
    try:
        from jaeger_os.main import boot_for_tui
        # prewarm_model=False: the generic two-pass prewarm primes a
        # DIFFERENT prefix (bare boot prompt + unfiltered registry
        # schemas) than the one the app's first turn actually sends, so
        # the first message re-prefilled everything anyway (~40 s
        # measured on gemma-4-E4B). prewarm_session below primes the
        # EXACT first-turn prefix instead — same warm-boot cost, zero
        # first-message delay.
        boot = boot_for_tui(instance_name=instance, prewarm_model=False)
    except Exception as exc:  # noqa: BLE001 — reported, never raised
        msg = str(exc)
        kind = "locked" if "lock" in msg.lower() else "boot"
        ctx.boot_error = msg
        _emit(proto, protocol.agent_state_frame("failed", error=msg))
        _emit(proto, protocol.fatal_frame(msg, kind=kind))
        ctx.booted.set()
        return

    ctx.boot = boot
    ctx.client = boot.client

    # Forward the agent loop's live tool activity as ``tool`` frames.
    class _ToolEmitter:
        def publish(self, event: str, **payload: object) -> None:
            if event == "tool.progress":
                _emit(proto, protocol.tool_frame(
                    str(payload.get("name", "")),
                    str(payload.get("phase", "start")),
                    float(payload.get("elapsed_s") or 0.0)))

    try:
        from jaeger_os.main import _pipeline
        _pipeline["event_bus"] = _ToolEmitter()
    except Exception:  # noqa: BLE001
        pass

    # Interactive permission approval over the wire (deny on timeout).
    try:
        from jaeger_os.core.safety.permissions import (
            AllowAllProvider, current_policy)
        policy = current_policy()
        if not isinstance(policy.confirmation, AllowAllProvider):
            policy.confirmation = _BridgeConfirm(proto, ctx)
    except Exception:  # noqa: BLE001
        pass

    # Prefix-exact KV prewarm for the app's chat session, BEFORE the
    # ready frame — the splash holds on agent_state "ready", so by the
    # time the operator can type, the first turn's whole prompt prefix
    # (session system prompt + tool schemas + resume digest) is already
    # prefilled and message #1 starts decoding immediately.
    try:
        from jaeger_os.main import prewarm_session
        prewarm_session(boot.client, session_key="desktop-app")
    except Exception:  # noqa: BLE001 — an optimization, never a boot failure
        pass

    # Scheduled prompts (reminders / timed tasks) fire here. The daemon
    # and the messaging gateway start a CronRunner; the bridge — now the
    # PRIMARY surface behind the native app — never did, so a
    # ``schedule_prompt`` persisted but nothing ever fired it. Start one
    # whose callback runs the scheduled prompt as a normal turn and
    # SURFACES the result as a reply frame, so a fired reminder shows up
    # in the chat (and speaks, when the instance voices its replies).
    #
    # ``llm_lock=None`` on purpose: ``_run_turn`` already serializes every
    # turn on ``_pipeline['llm_lock']`` internally, so a cron turn and a
    # user turn can't decode against the same KV cache at once. Handing
    # the SAME lock to the CronRunner would re-enter that non-reentrant
    # lock (cron acquires → callback → _run_turn re-acquires → deadlock).
    def _cron_cb(prompt: str, session_key: str | None = None) -> None:
        session = session_key or "cron"
        try:
            _emit(proto, protocol.state_frame(True, session))
            try:
                from jaeger_os.main import run_for_voice
                result = run_for_voice(ctx.client, prompt, session_key=session)
                text = result.get("text") or ""
                _emit(proto, protocol.reply_frame(
                    text, result.get("error"), session,
                    elapsed_s=result.get("elapsed_s")))
                # Speak a fired reminder when the instance voices its
                # replies and the turn didn't already speak via a tool.
                if text and not result.get("spoke_via_tool"):
                    try:
                        from jaeger_os.main import _pipeline
                        cfg = _pipeline.get("config")
                        if cfg is not None and cfg.voice.speak_replies:
                            from jaeger_os.agent.tools.speak import speak
                            speak(text=text)
                    except Exception as exc:  # noqa: BLE001 — TTS is best-effort
                        print(f"[bridge] cron speak failed: {exc}",
                              file=sys.stderr, flush=True)
            finally:
                _emit(proto, protocol.state_frame(False, session))
        except Exception as exc:  # noqa: BLE001 — a fired turn must never kill the bridge
            print(f"[bridge] cron turn failed: {exc}",
                  file=sys.stderr, flush=True)

    try:
        from jaeger_os.agent.background.cron_runner import CronRunner
        ctx.cron = CronRunner(_cron_cb, llm_lock=None)
        ctx.cron.start()
    except Exception as exc:  # noqa: BLE001 — no cron is degraded, not fatal
        print(f"[bridge] cron runner skipped: {exc}",
              file=sys.stderr, flush=True)

    name, icon = _active_character(boot)
    _emit(proto, protocol.agent_state_frame(
        "ready", model=_model_name(boot), character=name, icon=icon,
        agent_name=_agent_name(boot)))
    ctx.booted.set()


# Slash commands the bridge serves itself (the TUI's handlers, captured to
# text) — a SAFE subset of interfaces/tui/slash_commands.py: read-only /
# reporting handlers that never call ``console.input()``. The bridge's stdin
# is the protocol stream, so an interactive handler would eat protocol
# frames; anything conversational (goal / deepthink dialogs, model picker)
# and anything needing the live TUI (reboot, instance hot-switch) stays
# TUI-only and reports as such.
_SLASH_SAFE = ("help", "tools", "skills", "facts", "plugins",
               "instance", "instances", "models", "board", "config")


def _run_slash(text: str, ctx: "_Ctx") -> str:
    """Dispatch one slash line through the TUI's registry and return the
    rendered output as plain text. Python stays the single source of truth
    for slash behaviour — the client just displays what comes back."""
    from rich.console import Console
    from jaeger_os.interfaces.tui import slash_commands as sc

    name = (text.lstrip("/").split(None, 1) or [""])[0].lower()
    known = name in sc._BY_NAME  # noqa: SLF001 — same package family
    if known and name not in _SLASH_SAFE:
        return (f"/{name} needs the terminal TUI — it isn't available over "
                "the app bridge.\nAvailable here: "
                + "  ".join("/" + n for n in _SLASH_SAFE))
    # Capture the handler's Rich output as plain text (no ANSI, no markup).
    import io as _io
    console = Console(file=_io.StringIO(), record=True, width=88,
                      force_terminal=False, highlight=False)
    root = getattr(ctx.layout, "root", None)
    sctx = sc.SlashContext(console=console, instance_dir=root)
    result = sc.dispatch(text, sctx)
    if result.message:
        console.print(result.message)
    return console.export_text().rstrip() or "(no output)"


def _ctx_usage(session: str) -> tuple[int | None, int | None]:
    """Post-turn context telemetry for the reply frame (v1 additive):
    ``(used, max)`` tokens, or Nones when unavailable. ``used`` is the live
    prompt-size estimate for this session (system + history + schemas —
    the same gauge the TUI status bar shows); ``max`` is the loaded model's
    context window, falling back to ``config.model.ctx``."""
    used = mx = None
    try:
        from jaeger_os.main import _pipeline, last_ctx_snapshot
        snap = last_ctx_snapshot(session)
        if snap:
            used = int(snap["tokens"])
        loaded = int(getattr(_pipeline.get("client"), "loaded_ctx", 0) or 0)
        if loaded <= 0:
            cfg = _pipeline.get("config")
            loaded = int(getattr(getattr(cfg, "model", None), "ctx", 0) or 0)
        mx = loaded or None
    except Exception:  # noqa: BLE001 — telemetry never breaks a reply
        pass
    return used, mx


def _turn_worker(proto: TextIO, ctx: _Ctx,
                 turns: "_queue.Queue[dict[str, Any] | None]") -> None:
    """Runs chat turns off the stdin thread. Blocks each turn on boot
    completion — old clients that chat right after ``ready`` just wait,
    exactly as they did when ``ready`` meant model-loaded."""
    from jaeger_os.interfaces import protocol
    while True:
        req = turns.get()
        if req is None:
            return
        text = (req.get("text") or "").strip()
        session = req.get("session") or "desktop-app"
        # Slash pre-dispatch — same contract as the TUI REPL: a leading
        # ``/`` is a command, never a prompt for the model. Runs before
        # the boot wait so ``/help`` answers even while the model loads.
        if text.startswith("/"):
            _emit(proto, protocol.state_frame(True, session))
            try:
                reply = _run_slash(text, ctx)
                _emit(proto, protocol.reply_frame(reply, None, session))
            except Exception as exc:  # noqa: BLE001 — a bad command must not kill the bridge
                _emit(proto, protocol.reply_frame("", str(exc), session))
            finally:
                _emit(proto, protocol.state_frame(False, session))
            continue
        ctx.booted.wait()
        if ctx.client is None:
            _emit(proto, protocol.reply_frame(
                "", ctx.boot_error or "agent failed to boot", session))
            continue
        _emit(proto, protocol.state_frame(True, session))
        try:
            from jaeger_os.main import run_for_voice
            result = run_for_voice(ctx.client, text, session_key=session)
            used, mx = _ctx_usage(session)
            _emit(proto, protocol.reply_frame(
                result.get("text") or "", result.get("error"), session,
                elapsed_s=result.get("elapsed_s"),
                ctx_used=used, ctx_max=mx))
        except Exception as exc:  # noqa: BLE001 — a bad turn must not kill the bridge
            _emit(proto, protocol.reply_frame("", str(exc), session))
        finally:
            _emit(proto, protocol.state_frame(False, session))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    # The protocol stream is the REAL stdout.  Repoint sys.stdout at
    # stderr for the rest of the process so boot logs / stray prints land
    # on stderr and never corrupt the NDJSON the client is parsing.
    proto = sys.stdout
    sys.stdout = sys.stderr

    from jaeger_os.core.instance.instance import (
        InstanceLayout, default_instance_name, resolve_instance_dir)
    from jaeger_os.interfaces import protocol

    instance = (argv[0] if argv else None) or default_instance_name()

    ctx = _Ctx()
    # Cheap layout resolve — queries/commands work from here, no model needed.
    try:
        ctx.layout = InstanceLayout(resolve_instance_dir(instance))
    except Exception:  # noqa: BLE001 — queries will report per-call
        ctx.layout = None

    # FAST READY: the transport is usable now; the agent streams in behind.
    # Carry the agent's name (identity.yaml, on disk pre-boot) from the very
    # first frame so the tray/header never flashes the character name.
    _emit(proto, protocol.ready_frame(instance, None, agent="booting",
                                      agent_name=_agent_name(ctx)))

    # FIRST-RUN GUARD: with no instance on disk, ``boot_for_tui`` would
    # auto-fire the INTERACTIVE CLI wizard, whose ``input()`` reads
    # protocol JSON (or EOF) off OUR stdin and crashes the boot — the
    # 0.6 first-run break ("EOF when reading a line" → fatal boot).
    # Report ``no_instance`` instead and KEEP the transport alive:
    # queries/commands still work pre-instance, which is exactly what
    # the native app's onboarding flow runs on.
    if ctx.layout is None or not ctx.layout.exists():
        msg = (f"no instance named {instance!r} exists yet — "
               "first-run setup required")
        ctx.boot_error = msg
        _emit(proto, protocol.agent_state_frame("failed", error=msg))
        _emit(proto, protocol.fatal_frame(msg, kind="no_instance"))
        ctx.booted.set()
    else:
        _emit(proto, protocol.agent_state_frame("booting"))
        booter = threading.Thread(
            target=_boot_agent, args=(proto, ctx, instance),
            name="bridge-boot", daemon=True)
        booter.start()

    turns: "_queue.Queue[dict[str, Any] | None]" = _queue.Queue()
    worker = threading.Thread(
        target=_turn_worker, args=(proto, ctx, turns),
        name="bridge-turns", daemon=True)
    worker.start()

    # Queries need a layout-shaped object; before boot completes we hand
    # them a stub carrying just the layout (that's all _query reads).
    class _LayoutOnly:
        def __init__(self, layout: Any) -> None:
            self.layout = layout

    def _start_boot(inst: str) -> None:
        """(Re)start the background boot — used after ``create_instance``
        turns a no-instance transport into a real agent."""
        ctx.boot_error = None
        ctx.booted.clear()
        _emit(proto, protocol.agent_state_frame("booting"))
        threading.Thread(target=_boot_agent, args=(proto, ctx, inst),
                         name="bridge-boot", daemon=True).start()

    def _create_instance(args: dict[str, Any]) -> tuple[bool, Any, str | None]:
        """The ``create_instance`` command — first-run onboarding's write.
        Maps the client's answers onto the SAME non-interactive core the
        CLI wizard drives (setup_wizard.create_instance), then boots the
        fresh instance so ``agent_state`` streams booting → ready as the
        client's live "creating your Jaeger" progress."""
        from jaeger_os.core.instance.setup_wizard import create_instance
        cid = str(args.get("character_id") or "").strip()
        if not cid:
            return False, None, "character_id is required"
        try:
            lay = create_instance(
                character_id=cid,
                name=(args.get("name") or None),
                display_name=(args.get("display_name") or None),
                role=(args.get("role") or None),
                personality=(args.get("personality") or None),
                voice_id=(args.get("voice_id") or None),
                awake_model=(args.get("awake_model") or None),
                asleep_model=(args.get("asleep_model") or None),
                permission_mode=str(args.get("permission_mode") or "confirm"),
                interaction_mode=str(args.get("interaction_mode") or "gui"),
            )
        except Exception as exc:  # noqa: BLE001 — reported, never crashes the bridge
            return False, None, str(exc)
        ctx.layout = lay
        return True, {"instance": lay.root.name, "root": str(lay.root)}, None

    rc = 0
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
            op = req.get("op")
            if op == "quit":
                break
            if op == "respond":
                rid = str(req.get("id") or "")
                pending = ctx.pending.get(rid)
                if pending is not None:
                    evt, slot = pending
                    slot.append(str(req.get("answer") or ""))
                    evt.set()
                else:
                    ctx.early[rid] = str(req.get("answer") or "")
                continue
            if op == "command" and (req.get("cmd") or "") == "settings_set":
                # Schema-derived settings write — validates + persists via
                # core/settings/catalog.set_value (the SAME backend `jaeger
                # settings set` calls). Handled here (not _command) so the
                # result frame can carry ``restart_required`` in its data.
                # Uses ctx.layout directly: settings work pre-boot / while
                # the model warms, matching the fast-ready design.
                a = req.get("args") or {}
                try:
                    from jaeger_os.core.settings.catalog import set_value
                    res = set_value(ctx.layout, str(a.get("path") or ""),
                                    a.get("value"))
                    _emit(proto, protocol.result_frame(
                        req.get("id"),
                        data={"restart_required": res["restart_required"],
                              "path": res["path"], "value": res["value"]},
                        ok=True))
                except Exception as exc:  # noqa: BLE001 — reported, never crashes
                    _emit(proto, protocol.result_frame(
                        req.get("id"), ok=False, error=str(exc)))
                continue
            if op == "command" and (req.get("cmd") or "") == "create_instance":
                # Handled here (not in _command): it needs ctx + proto to
                # restart the boot thread against the new instance. The
                # result goes out FIRST so the client sees ok before the
                # agent_state booting → ready progress starts streaming.
                ok, data, err = _create_instance(req.get("args") or {})
                _emit(proto, protocol.result_frame(
                    req.get("id"), data=data, ok=ok, error=err))
                if ok:
                    _start_boot(data["instance"])
                continue
            if op in ("query", "command"):
                target = ctx.boot if ctx.boot is not None else _LayoutOnly(ctx.layout)
                if op == "query":
                    try:
                        data = _query(req.get("what") or "", req.get("args") or {}, target)
                        _emit(proto, protocol.result_frame(req.get("id"), data=data))
                    except Exception as exc:  # noqa: BLE001
                        _emit(proto, protocol.result_frame(
                            req.get("id"), ok=False, error=str(exc)))
                else:
                    ok, err = _command(req.get("cmd") or "", req.get("args") or {}, target)
                    _emit(proto, protocol.result_frame(req.get("id"), ok=ok, error=err))
                continue
            # ``{"op":"send","text":...}`` (protocol) or legacy ``{"text":...}``.
            if (req.get("text") or "").strip():
                turns.put(req)
    finally:
        # Orderly shutdown: let the boot settle (can't clean up a
        # half-booted agent), stop the worker, tear down, mark the exit
        # clean, then leave through os._exit if the Metal runtime is
        # loaded (its C++ static destructors abort — F1).
        ctx.booted.wait(timeout=180)
        # Stop the scheduled-prompt thread before tearing down the agent
        # it fires turns against.
        if ctx.cron is not None:
            try:
                ctx.cron.shutdown(wait=False)
            except Exception:  # noqa: BLE001 — best-effort teardown
                pass
        turns.put(None)
        worker.join(timeout=30)
        if ctx.boot_error:
            rc = 1
        boot = ctx.boot
        cleanup = getattr(boot, "cleanup", None) if boot is not None else None
        if callable(cleanup):
            try:
                cleanup()
            except Exception:  # noqa: BLE001 — best-effort teardown
                pass
        _emit(proto, protocol.bye_frame())
        if "llama_cpp" in sys.modules or "_pywhispercpp" in sys.modules:
            try:
                proto.flush()
                sys.stderr.flush()
            except Exception:  # noqa: BLE001
                pass
            os._exit(rc)

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
