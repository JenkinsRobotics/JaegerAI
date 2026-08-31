"""Headless NDJSON stdio bridge — the agent pipeline behind the native app.

The Swift shell spawns ``jaeger bridge`` and exchanges newline-delimited
JSON over stdin/stdout — the same agent turn the TUI runs, one hop out of
process.  Protocol v1 lives in ``jaeger_os/contract/protocol.py`` (the
single wire contract, 0.9 contract package) with
``jaeger_os/contract/protocol_v1_fixtures.json`` as the cross-language
test fixtures.

Phase-1 hardening (SWIFT_APP_ARCHITECTURE_PLAN.md, approved 2026-07-04):

  * FAST READY — ``ready`` is emitted the moment the TRANSPORT is usable
    (layout resolved; queries/commands work immediately).  The model boots
    on a background thread; ``agent_state`` frames stream
    ``booting → ready | failed`` so the shell separates "UI usable" from
    "agent warm".  Chat turns queue and BLOCK until boot completes, so
    older clients (JaegerClient) keep their semantics.
  * WORKER-THREAD TURNS — the stdin loop never blocks on a turn, so
    ``respond`` (permission answers) and ``quit`` stay processable mid-turn.
  * INTERACTIVE PERMISSIONS — tier-2+ approval requests surface as
    ``request`` frames (kind=approval, options once/always/deny);
    ``{"op":"respond","id":…,"answer":…}`` resolves them (timeout ⇒ deny,
    fail-safe). ``always`` persists a per-skill grant to the SAME
    ``<instance>/permissions.json`` the console provider reads/writes —
    see :class:`BridgeConfirmationProvider`. 0.9.3 Task 1: the surface
    that unblocks tier-2 tools (``open_on_host``, …) for GUI/headless
    stations that have no console to prompt at.
  * CLEAN-EXIT MARKER — ``bye`` is emitted before exit, and the process
    leaves through ``os._exit`` past the ggml Metal teardown abort (F1),
    so the client can trust "bye seen = orderly, no bye = crash".

stdout carries ONLY protocol JSON — model-boot logs, llama.cpp chatter,
and any stray ``print`` are forced to stderr so they can't corrupt the
stream.  Run via ``jaeger bridge`` (the shim picks the .venv interpreter)
or ``python -m jaeger_os.interfaces.bridge [instance_name]``.
"""

from __future__ import annotations

import errno
import json
import os
import queue as _queue
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, TextIO

from jaeger_ai.interfaces import pidfile

_emit_lock = threading.Lock()


def _emit(out: TextIO, obj: dict[str, Any]) -> None:
    """Write one protocol line and flush — the client reads line-by-line.
    Locked: the turn worker and the stdin thread share one stream.

    A detached Unix-socket client must not kill the instance-wide turn worker.
    Owner stdio failures still propagate because they mean the bridge itself
    has lost its controlling transport.
    """
    with _emit_lock:
        try:
            out.write(json.dumps(obj, ensure_ascii=False) + "\n")
            out.flush()
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
            if getattr(out, "_jaeger_attach_stream", False):
                return
            raise


def _emit_state(out: TextIO, ctx: _Ctx, busy: bool, session: str = "") -> None:
    """Emit a ``state`` frame AND flip ``ctx.busy`` — the single place a
    turn (chat/slash/cron) marks itself in flight, so ``run_update``'s
    guard and the wire frame never drift apart."""
    ctx.busy = busy
    from jaeger_os.contract import protocol
    _emit(out, protocol.state_frame(busy, session))


def _model_name(boot: Any) -> str | None:
    """Best-effort model label for the status line; None if unknown.

    Uses the serving brain (the model THIS session is talking to), not
    the idle local mode preset. The client's status bar falls back to
    the instance name when this is null, so a miss here is cosmetic,
    not fatal."""
    try:
        from jaeger_ai.core.runtime.modes import serving_brain
        name = serving_brain().get("model")
        if isinstance(name, str) and name.strip():
            return name.rsplit("/", 1)[-1]
    except Exception:  # noqa: BLE001
        pass
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
    """The active character's display name + the agent's effective avatar path
    (see ``_effective_icon``) — for the native client's tray/header. Best-effort;
    a miss is cosmetic."""
    try:
        from jaeger_ai.personality.character import active_character
        root = getattr(getattr(boot, "layout", None), "root", None)
        if root is not None:
            c = active_character(root)
            if c is not None:
                return c.name, _effective_icon(boot, c)
    except Exception:  # noqa: BLE001
        pass
    return None, None


def _effective_icon(boot: Any, character: Any) -> str | None:
    """The agent's avatar path: the instance profile picture (identity.avatar)
    if set and present, else the active character's card. So the agent keeps
    its own face once the operator sets one, while a fresh instance still shows
    the character card as a default (which follows a persona switch)."""
    from pathlib import Path
    try:
        from jaeger_ai.core.instance.schemas import Identity, load_yaml
        lay = getattr(boot, "layout", None)
        avatar = (load_yaml(lay.identity_path, Identity).avatar or "").strip()
        if avatar:
            p = Path(avatar)
            if not p.is_absolute():
                p = Path(lay.root) / avatar
            if p.is_file():
                return str(p)
    except Exception:  # noqa: BLE001 — cosmetic; fall back to the character card
        pass
    icon = character.icon_path() if character is not None else None
    return str(icon) if icon else None


# Card art is a portrait PNG (320x420 from ``generate_card``) — a few
# hundred KB at most. The cap is a wire sanity bound, not a policy: a
# frame this size is fine, a multi-megabyte one would stall the stdio
# transport every surface shares.
_CARD_MAX_BYTES = 4 * 1024 * 1024
_PROMPT_FILE_MAX_BYTES = 2 * 1024 * 1024

_CARD_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp",
}


def _card_art(path: str | None, character_id: str) -> dict[str, Any] | None:
    """Read a character's card into a base64 frame, or ``None``.

    Never raises: a missing or oversized card means the surface draws its
    own placeholder, which is a cosmetic outcome, not an error.
    """
    from base64 import b64encode
    from pathlib import Path

    if not path:
        return None
    p = Path(path)
    try:
        if not p.is_file():
            return None
        size = p.stat().st_size
        if size > _CARD_MAX_BYTES:
            return None
        data = p.read_bytes()
    except OSError:
        return None
    return {
        "id": character_id,
        "mime": _CARD_MIME.get(p.suffix.lower(), "application/octet-stream"),
        "bytes": len(data),
        "filename": p.name,
        "data": b64encode(data).decode("ascii"),
    }


def _request_text(req: dict[str, Any]) -> tuple[str, str | None]:
    """Resolve inline text plus an optional file-backed prompt.

    ``prompt_path`` keeps large prompts out of terminal canonical-line
    buffers while preserving NDJSON framing. Reading a file is explicit in
    the request, bounded, UTF-8 only, and errors are returned on the normal
    reply rail instead of silently turning into an empty prompt.
    """
    inline = str(req.get("text") or "").strip()
    raw_path = str(req.get("prompt_path") or "").strip()
    if not raw_path:
        return inline, None
    path = Path(raw_path).expanduser()
    try:
        size = path.stat().st_size
        if not path.is_file():
            return "", f"prompt_path is not a file: {path}"
        if size > _PROMPT_FILE_MAX_BYTES:
            return "", (
                f"prompt_path exceeds {_PROMPT_FILE_MAX_BYTES} bytes: {path}"
            )
        body = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        return "", f"could not read prompt_path {path}: {exc}"
    if not body:
        return "", f"prompt_path is empty: {path}"
    return (f"{inline}\n\n{body}" if inline else body), None


# ── text deltas ──────────────────────────────────────────────────────
#
# A turn used to reach an external surface as one ``reply`` frame at the
# end, so a remote client showed nothing for the whole generation and
# then everything at once. The loop has always streamed internally (the
# TUI and the TTS sentence-chunker consume ``on_stream_delta``); this is
# that stream, published on the wire.
#
# Coalescing: one frame per token would be hundreds of JSON encodes and
# flushes a second on a fast model, and the reader on the other end is a
# browser that repaints at 60Hz regardless. The FIRST chunk always goes
# out immediately — time-to-first-token is the number a person feels —
# and after that frames are batched until either threshold trips.
_DELTA_MIN_CHARS = 32
_DELTA_MAX_INTERVAL_S = 0.08


# ``delta_frame`` moved into ``jaeger_os.contract.protocol`` beside its
# siblings during the monorepo absorption, exactly as the note that used to
# live here asked for once JaegerOS stopped being a tag-pinned dependency.
# These thin wrappers keep the private names working for callers in this
# module. ``protocol`` is imported lazily throughout this file (module-level
# import would drag JaegerOS in at bridge-import time), so they defer too.
def _delta_frame(text: str, session: str = "") -> dict[str, Any]:
    from jaeger_os.contract import protocol

    return protocol.delta_frame(text, session)


def _reasoning_frame(text: str, session: str = "") -> dict[str, Any]:
    from jaeger_os.contract import protocol

    return protocol.reasoning_frame(text, session)


class _DeltaStream:
    """Buffers token text and emits coalesced ``delta`` frames.

    Not thread-safe by design — it is driven from the decode loop of one
    turn, which is serialized by the pipeline's llm_lock.
    """

    def __init__(self, out: TextIO, session: str) -> None:
        self._out = out
        self._session = session
        self._buf: list[str] = []
        self._pending = 0
        self._last_flush = 0.0
        self._sent = 0          # characters actually put on the wire
        self._started = False

    def feed(self, piece: str) -> None:
        text = str(piece or "")
        if not text:
            return
        self._buf.append(text)
        self._pending += len(text)
        now = time.monotonic()
        if not self._started:
            # First token out the door immediately: this is the latency
            # the operator actually perceives.
            self._started = True
            self.flush(now)
            return
        if (self._pending >= _DELTA_MIN_CHARS
                or (now - self._last_flush) >= _DELTA_MAX_INTERVAL_S):
            self.flush(now)

    def flush(self, now: float | None = None) -> None:
        if not self._buf:
            return
        text = "".join(self._buf)
        self._buf.clear()
        self._pending = 0
        self._last_flush = time.monotonic() if now is None else now
        self._sent += len(text)
        _emit(self._out, _delta_frame(text, self._session))

    @property
    def sent_chars(self) -> int:
        """How much text this turn actually streamed — the client uses it
        to avoid re-rendering the same prefix when the reply lands."""
        return self._sent


_LAYERS = ("hexaco", "special", "expression", "domains")

# Additive application contract carried inside protocol v1's generic query
# envelope.  The wire protocol describes frame shapes; this contract describes
# which product features this Jaeger build actually implements.  Clients must
# feature-gate from this response instead of inferring support from versions or
# repository names.
# 10: ``identity`` carries ``display_name`` and character rows carry
# ``neutral`` — the single-identity projection (2026-08-19).
# 12: ``cron`` query reports in-flight scheduled jobs so a host sidebar
# can keep those sessions marked running until the callback returns.
# 13: ``model_picker`` query — Hermes-style two-stage catalog for the
# windowed ``/model`` overlay (clickable, not a transcript dump).
INTEGRATION_CONTRACT_VERSION = 13
BRIDGE_QUERIES = (
    "contract", "identity", "characters", "character", "character_card",
    "config",
    "serving_model", "settings_catalog", "permissions", "instance_exists",
    "setup_defaults", "model_catalog", "model_picker", "session_contract", "list_sessions", "load_session",
    "search_sessions", "check_update",
    "list_skills", "get_skill", "list_mcp_servers", "list_tools",
    "list_credentials", "skill_usage",
    "board", "heartbeat", "cron", "list_schedules",
)
BRIDGE_COMMANDS = (
    "select_character", "make_default", "save_profile", "save_traits",
    "save_config", "save_identity", "revoke_permission", "speak",
    "settings_set", "run_update", "new_session", "create_instance",
    "clone_skill", "install_skill", "enable_skill", "disable_skill", "remove_skill",
    "configure_mcp_server", "enable_mcp_server", "disable_mcp_server",
    "remove_mcp_server", "reload_tools",
    "set_credential", "delete_credential",
    "configure_model", "configure_fallback_chain",
    "create_session", "clear_session", "delete_session", "reconcile_session_transcript",
    "create_schedule", "cancel_schedule", "pause_schedule", "resume_schedule",
)


def _session_contract() -> dict[str, Any]:
    """Versioned ownership contract consumed by ARES and native surfaces."""
    from jaeger_ai.core.sessions import SESSION_CONTRACT_VERSION

    return {
        "name": "ares-jaeger-sessions",
        "version": SESSION_CONTRACT_VERSION,
        "identifier": {
            "format": "opaque",
            "max_length": 256,
            "emits_namespaces": False,
        },
        "ownership": {
            "transcript": "jaeger",
            "execution_state": "jaeger",
            "tool_calls": "jaeger",
            "runtime_history": "jaeger",
            "workspace": "ares",
            "project": "ares",
            "pin": "ares",
            "archive": "ares",
            "display_title": "ares",
            "draft": "ares",
        },
        "operations": {
            "create": {"available": True, "owner": "jaeger", "mutable": True},
            "list": {"available": True, "owner": "jaeger", "mutable": False},
            "load": {"available": True, "owner": "jaeger", "mutable": False},
            "rename": {"available": True, "owner": "ares", "mutable": True},
            "clear": {"available": True, "owner": "jaeger", "mutable": True},
            "delete": {"available": True, "owner": "jaeger", "mutable": True},
            "archive": {"available": True, "owner": "ares", "mutable": True},
            "search": {"available": True, "owner": "jaeger", "mutable": False},
        },
        "idempotent_mutations": ["create", "rename", "clear", "delete", "archive"],
        "tombstones": {"owner": "jaeger", "durable": True},
    }


def _integration_contract() -> dict[str, Any]:
    """Return the authoritative feature contract for external surfaces."""
    from jaeger_os.contract import protocol

    from jaeger_ai import __version__
    from jaeger_ai.interfaces.surface_contract import (
        SWIFT_COMMAND_SUPPORT,
        SWIFT_QUERY_SUPPORT,
    )

    return {
        "contract": "ares-jaeger",
        "contract_version": INTEGRATION_CONTRACT_VERSION,
        "scope": "runtime_provider",
        "protocol_version": str(protocol.PROTOCOL_VERSION),
        "runtime": {"id": "jaeger_local", "name": "JaegerAI", "version": __version__},
        "operations": {
            "queries": list(BRIDGE_QUERIES),
            "commands": list(BRIDGE_COMMANDS),
            "controls": ["cancel", "steer", "respond"],
        },
        "surface_support": {
            "swift": {
                "queries": dict(SWIFT_QUERY_SUPPORT),
                "commands": dict(SWIFT_COMMAND_SUPPORT),
            },
        },
        "domains": {
            "agent_runtime": [
                "chat", "sessions", "approvals", "schedules", "runtime_settings",
                "character_persona_editing", "voice_settings",
            ],
            "extensibility": ["skills", "mcp_server_config", "tool_inventory"],
        },
        "features": {
            "chat": {"available": True, "owner": "jaeger", "mutable": True},
            "sessions": {
                "available": True, "owner": "jaeger", "mutable": True,
                "contract": _session_contract(),
            },
            "approvals": {"available": True, "owner": "jaeger", "mutable": True},
            "schedules": {"available": True, "owner": "jaeger", "mutable": True},
            "character_persona_editing": {
                "available": True, "owner": "jaeger", "mutable": True,
            },
            # v8 additive: a surface can render the agent's FACE without
            # reaching into this product's directories — Jaeger serves the
            # bytes for the asset it owns. Clients feature-gate on this
            # entry (or on "character_card" in operations.queries), never
            # on a version number.
            # v9 additive: the turn's text arrives incrementally as
            # ``delta`` frames while it generates, ahead of the final
            # ``reply``. A client that does not know the frame ignores it
            # and still gets the whole answer in ``reply`` — so this is
            # safe in both directions, and clients gate on this entry
            # rather than on a version number.
            "text_deltas": {
                "available": True, "owner": "jaeger", "mutable": False,
                "frame": "delta", "coalesce_chars": _DELTA_MIN_CHARS,
                "coalesce_interval_s": _DELTA_MAX_INTERVAL_S,
            },
            "character_card_art": {
                "available": True, "owner": "jaeger", "mutable": False,
                "encoding": "base64", "max_bytes": _CARD_MAX_BYTES,
            },
            "runtime_settings": {"available": True, "owner": "jaeger", "mutable": True},
            "voice_settings": {"available": True, "owner": "jaeger", "mutable": True},
            "updates": {"available": True, "owner": "jaeger", "mutable": True},
            "skills": {"available": True, "owner": "jaeger", "mutable": True},
            "mcp_server_config": {
                "available": True, "owner": "jaeger", "mutable": True,
                "transports": ["stdio", "streamable_http"],
            },
            "tool_inventory": {"available": True, "owner": "jaeger", "mutable": False},
            "board": {"available": True, "owner": "jaeger", "mutable": False},
            "heartbeat": {"available": True, "owner": "jaeger", "mutable": True},
            "cron": {"available": True, "owner": "jaeger", "mutable": False},
            "fallback_chain": {"available": True, "owner": "jaeger", "mutable": True},
            "webhooks": {"available": True, "owner": "jaeger", "mutable": True},
            "credentials": {"available": True, "owner": "jaeger", "mutable": True,
                            "values_readable": False},
            "runtime_logs": {"available": False, "owner": "jaeger", "mutable": False},
            "runtime_memory": {"available": False, "owner": "jaeger", "mutable": False},
        },
    }


_CRON_RUNNING: dict[str, float] = {}
_CRON_RUNNING_LOCK = threading.Lock()


def _cron_job_name(session_key: str | None) -> str:
    raw = str(session_key or "cron").strip() or "cron"
    if raw.startswith("cron:"):
        return raw[5:] or "cron"
    if raw.startswith("cron_"):
        return raw[5:] or "cron"
    return raw


def _mark_cron_running(name: str) -> None:
    job = str(name or "").strip()
    if not job:
        return
    with _CRON_RUNNING_LOCK:
        _CRON_RUNNING[job] = time.time()


def _mark_cron_done(name: str) -> None:
    job = str(name or "").strip()
    if not job:
        return
    with _CRON_RUNNING_LOCK:
        _CRON_RUNNING.pop(job, None)


def _cron_running_snapshot() -> dict[str, float]:
    with _CRON_RUNNING_LOCK:
        return dict(_CRON_RUNNING)


def _session_cron_running(sid: str, running: dict[str, float] | None = None) -> bool:
    """True when ``sid`` belongs to a cron job currently in ``_CRON_RUNNING``.

    Jaeger fires as ``cron:<name>``. ARES/Hermes session ids are
    ``cron_{job_id}_{YYYYMMDD_HHMMSS}``. Either shape must light the
    sidebar spinner for the live run only.
    """
    jobs = _cron_running_snapshot() if running is None else running
    if not sid or not jobs:
        return False
    if sid in jobs:
        return True
    if sid.startswith("cron:"):
        return sid[5:] in jobs
    for name in jobs:
        prefix = f"cron_{name}_"
        if sid.startswith(prefix) and len(sid) == len(prefix) + 15:
            # YYYYMMDD_HHMMSS is 15 characters.
            return True
    return False


def _stamp_cron_running(rows: list[Any]) -> list[Any]:
    running = _cron_running_snapshot()
    if not running:
        for row in rows:
            if isinstance(row, dict):
                row["cron_running"] = False
        return rows
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("session_id") or row.get("id") or "")
        row["cron_running"] = _session_cron_running(sid, running)
    return rows


def _agent_name(boot: Any) -> str | None:
    """The AGENT's own name (identity.yaml — the unique robot the operator
    named), NEVER the character. Every branded surface leads with this."""
    try:
        from jaeger_ai.core.instance.schemas import Identity, load_yaml
        lay = getattr(boot, "layout", None)
        return (load_yaml(lay.identity_path, Identity).name or "").strip() or None
    except Exception:  # noqa: BLE001 — cosmetic; surfaces fall back to character
        return None


def _display_name(boot: Any) -> str | None:
    """The one name the agent answers to right now — the active
    character's, or the instance's own while the neutral ``assistant``
    sheet is selected. Best-effort; a miss is cosmetic and the surface
    falls back to ``agent_name``."""
    try:
        from jaeger_ai.personality.character import (
            active_character,
            persona_display_name,
        )
        root = _instance_root(boot)
        character = active_character(root) if root is not None else None
        return persona_display_name(_agent_name(boot) or "", character) or None
    except Exception:  # noqa: BLE001
        return _agent_name(boot)


def _instance_root(boot: Any) -> Any:
    return getattr(getattr(boot, "layout", None), "root", None)


def _suggested_name(instance: str | None) -> str | None:
    """The operator-pinned instance name to hand onboarding as a
    ``suggested_name``, or None when there's nothing real to suggest.

    ``instance`` is whatever ``main()`` resolved to boot/attach against —
    an explicit CLI pin (``./jaeger agent create lilith`` → argv[0]) OR
    the generic ``default_instance_name()`` fallback, and the two are
    indistinguishable once they reach here (``_launch_swift_app`` pins
    ``JAEGER_INSTANCE_NAME`` unconditionally — see main.py:3610). The
    literal ``"default"`` is that fallback's own conjured placeholder
    (never a name an operator typed), so it's the one value filtered
    out — everything else (an explicit CLI name, or a sticky default
    from a prior ``jaeger instance use``) is a real name worth
    prefilling."""
    name = (instance or "").strip()
    return name if name and name != "default" else None


def _char_summary(c: Any, active_id: Any, bound_id: Any) -> dict[str, Any]:
    from jaeger_ai.personality.character import layer_items
    stats: list[dict[str, Any]] = []
    for layer in _LAYERS:
        sub = getattr(c.personality, layer, None)
        if sub is not None:
            stats += [{"key": k, "val": float(v)} for k, v in layer_items(sub)]
    icon = c.icon_path()
    card = c.card_path()
    # v1 additive ``neutral``: True for the one sheet that is nobody in
    # particular (``assistant``). A surface shows the INSTANCE's name for
    # that row and the CHARACTER's name for every other — same rule the
    # prompt follows (personality/character.py persona_display_name).
    return {"id": c.id, "name": c.name, "role": c.role, "level": c.level,
            "revision": c.revision, "icon": str(icon) if icon else None,
            "card": str(card) if card else None, "neutral": bool(c.neutral),
            "active": c.id == active_id, "bound": c.id == bound_id, "stats": stats}


def _char_detail(c: Any) -> dict[str, Any]:
    from jaeger_ai.personality.character import layer_items
    traits: dict[str, dict[str, float]] = {}
    for layer in _LAYERS:
        sub = getattr(c.personality, layer, None)
        if sub is not None:
            traits[layer] = {k: round(float(v), 3) for k, v in layer_items(sub)}
    icon = c.icon_path()
    return {"id": c.id, "name": c.name, "role": c.role, "level": c.level,
            "neutral": bool(c.neutral),
            "voice_tone": c.voice_tone, "voice_id": c.voice_id,
            "soul": c.soul, "backstory": c.backstory,
            "custom_instructions": getattr(c.personality, "custom_instructions", ""),
            "icon": str(icon) if icon else None, "traits": traits}


def _runtime_bound() -> bool:
    from jaeger_agent.memory import sqlite_store
    return sqlite_store.is_bound()


def _runtime_query_runs(args: dict[str, Any]) -> list[dict[str, Any]]:
    if not _runtime_bound():
        return []
    from dataclasses import asdict

    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
    return [asdict(run) for run in SqliteRunStore().list(
        commitment_id=args.get("commitment_id"),
        state=args.get("state"),
    )]


def _runtime_query_commitments(args: dict[str, Any]) -> list[dict[str, Any]]:
    if not _runtime_bound():
        return []
    from dataclasses import asdict

    from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
    return [asdict(item) for item in SqliteCommitmentStore().list(
        state=args.get("state"),
    )]


def _runtime_query_effects(args: dict[str, Any]) -> list[dict[str, Any]]:
    if not _runtime_bound():
        return []
    from dataclasses import asdict

    from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
    status = args.get("status", "pending")
    return [asdict(item) for item in SqliteEffectLedger().list(status=status)]


def _runtime_deliver_event(wake_key: str) -> tuple[bool, str | None]:
    if not wake_key:
        return False, "wake_key is required"
    if not _runtime_bound():
        return False, "runtime store is not bound"
    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
    woken = SqliteRunStore().deliver_event(wake_key)
    return True, None if woken is not None else "deliver failed"


def _runtime_resolve_effect(key: str, result: Any) -> tuple[bool, str | None]:
    if not key:
        return False, "key is required"
    if not _runtime_bound():
        return False, "runtime store is not bound"
    from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
    try:
        SqliteEffectLedger().resolve(key, result)
    except Exception as exc:  # noqa: BLE001 — command reports, never crashes
        return False, str(exc)
    return True, None


def _runtime_abandon_effect(key: str) -> tuple[bool, str | None]:
    if not key:
        return False, "key is required"
    if not _runtime_bound():
        return False, "runtime store is not bound"
    from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
    try:
        SqliteEffectLedger().abandon(key)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    return True, None


def _query(what: str, args: dict[str, Any], boot: Any) -> Any:
    """Read-only accessors for the native settings HUD — the same data the
    PySide6 window reads, over the pipe."""
    from jaeger_ai.personality.character import (
        active_character,
        active_character_id,
        bound_character_id,
        list_characters,
    )
    root = _instance_root(boot)
    lay = getattr(boot, "layout", None)
    if what == "contract":
        return _integration_contract()
    if what == "list_skills":
        from jaeger_ai.core.skills.service import list_skills

        return list_skills(lay)
    if what == "get_skill":
        from jaeger_ai.core.skills.service import get_skill

        return get_skill(lay, str(args.get("name") or ""), args.get("file"))
    if what == "list_mcp_servers":
        from jaeger_ai.core.mcp.service import list_servers

        return list_servers(lay)
    if what == "list_tools":
        from jaeger_ai.core.mcp.service import list_tools

        return list_tools(lay)
    if what == "list_credentials":
        from jaeger_ai.core.credential_service import list_credentials

        return list_credentials(lay)
    if what == "identity":
        # The agent's live identity for tray/header/orb branding — cheap
        # enough to re-ask after a character switch (the client refreshes
        # this instead of waiting for the next agent_state frame).
        # ``agent_name`` is the instance's own name (identity.yaml) and
        # ``character`` the selected sheet; ``display_name`` — v1 additive,
        # 2026-08-19 — is the one name the agent actually answers to, and
        # is what every surface should show. The character's name wins
        # while a character is selected; the instance's own comes through
        # only for the neutral sheet. Surfaces used to render "Ted ·
        # playing HAL 9000", which is two identities where the operator
        # picked one. See personality/character.py persona_display_name.
        name, icon = _active_character(boot)
        # ``avatar`` = the raw CUSTOM profile picture (None → the effective
        # ``icon`` is the character card). Surfaces use it to decide whether a
        # persona switch should OFFER to adopt the new character's card.
        avatar = None
        try:
            from jaeger_ai.core.instance.schemas import Identity, load_yaml
            avatar = load_yaml(lay.identity_path, Identity).avatar
        except Exception:  # noqa: BLE001
            avatar = None
        cid = None
        try:
            cid = active_character_id(root) if root is not None else None
        except Exception:  # noqa: BLE001
            cid = None
        return {"agent_name": _agent_name(boot), "character": name, "icon": icon,
                "character_id": cid,
                "display_name": _display_name(boot), "avatar": avatar,
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
    if what == "character_card":
        # The card art for a character (default: whoever is active), as
        # bytes. External surfaces get the image through the bridge
        # rather than by reading this product's install directory — a
        # path across the boundary is not readable by a browser anyway,
        # and the ownership contract says the asset's owner serves it.
        cid = args.get("id")
        c = next((x for x in list_characters() if x.id == cid), None) if cid else None
        if c is None and root is not None:
            c = active_character(root)
        if c is None:
            return None
        return _card_art(_effective_icon(boot, c), c.id)
    if what == "board":
        from jaeger_agent.background.board import (
            board_digest,
            board_for_layout,
            has_actionable_work,
        )
        if lay is None:
            return {"cards": [], "digest": "", "has_actionable": False}
        try:
            cards = [c.to_dict() for c in board_for_layout(lay).list()]
        except Exception:  # noqa: BLE001
            cards = []
        return {
            "cards": cards,
            "digest": board_digest(lay),
            "has_actionable": has_actionable_work(lay),
        }
    if what == "heartbeat":
        from jaeger_ai.core.instance.schemas import Config, load_yaml
        from jaeger_ai.core.runtime import heartbeat as _hb
        enabled, interval = True, 30
        if lay is not None:
            try:
                cfg = load_yaml(lay.config_path, Config)
                enabled = bool(cfg.heartbeat.enabled)
                interval = int(cfg.heartbeat.interval_minutes)
            except Exception:  # noqa: BLE001
                pass
        return _hb.status(lay, interval_minutes=interval, enabled=enabled)
    if what == "cron":
        from jaeger_ai.core.runtime.schedules import list_jobs

        jobs = list_jobs()
        return {
            "running": _cron_running_snapshot(),
            "scheduler": "jaeger",
            "jobs": jobs.get("schedules") or [],
            "count": int(jobs.get("count") or 0),
        }
    if what == "list_schedules":
        from jaeger_ai.core.runtime.schedules import list_jobs

        return list_jobs()
    if what == "config":
        from jaeger_ai.core.instance.schemas import Config, Identity, load_yaml
        cfg = load_yaml(lay.config_path, Config)
        ident = load_yaml(lay.identity_path, Identity)
        # v1 additive: ``avatar`` = the raw custom profile picture (None → the
        # tab shows "using the character card"); ``avatar_effective`` = the
        # resolved path actually displayed (custom, else the character card).
        return {"name": ident.name, "role": ident.role,
                "avatar": ident.avatar,
                "avatar_effective": _effective_icon(
                    boot, active_character(root) if root else None),
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
                "model_aux_ctx": cfg.model.aux_ctx,
                "heartbeat_enabled": cfg.heartbeat.enabled,
                "heartbeat_interval_minutes": cfg.heartbeat.interval_minutes}
    if what == "serving_model":
        # The model ACTUALLY answering, for hosts (ARES) that must show the
        # truth rather than the selection they requested. Deliberately not
        # derived from config: ``external_model.enabled`` is an intent, and a
        # cloud lane that failed to start leaves that intent in the file
        # while a local model answers. ``fallback_active`` says so out loud;
        # a host must never report a cloud model when this is True.
        # Pre-boot (no client yet) returns ``booted: False`` with the
        # configured intent, so a caller can distinguish "not yet" from
        # "something else is serving".
        from jaeger_ai.core.models.model_resolver import serving_model

        row = serving_model()
        if row is None:
            intent: dict[str, Any] = {"booted": False, "serving": None}
            try:
                from jaeger_ai.core.instance.schemas import Config, load_yaml

                cfg = load_yaml(lay.config_path, Config)
                ext = cfg.external_model
                intent["configured"] = {
                    "provider": ext.provider if ext.enabled else "in-process",
                    "model": ext.model if ext.enabled else cfg.model.model_path,
                    "context_length": (ext.ctx or cfg.model.ctx) or None,
                }
            except Exception:  # noqa: BLE001
                intent["configured"] = None
            return intent
        return {"booted": True, "serving": row}

    if what == "model_catalog":
        """Canonical model inventory for external product surfaces."""
        from jaeger_ai.core.models.model_resolver import (
            list_registered_models,
            serving_model,
        )

        raw_models = list_registered_models()
        models: list[dict[str, Any]] = []
        providers: dict[str, dict[str, Any]] = {}
        for row in raw_models:
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("name") or row.get("filename") or "").strip()
            if not model_id:
                continue
            route_provider = str(row.get("provider") or "").strip() or None
            location = str(row.get("location") or row.get("kind") or "unknown")
            # The signed-in host Ollama daemon is the transport for both
            # on-device and hosted models.  Keep that routing fact internal:
            # product surfaces need the user-facing provider boundary, not
            # the socket used to reach it.
            provider = route_provider
            if route_provider == "ollama":
                provider = "ollama-cloud" if location == "cloud" else "ollama-local"
            # Same model id can exist on Ollama Cloud AND local Ollama.
            # The label has to say which, or a picker keyed by id alone
            # will start the local daemon for a cloud pick.
            label = str(row.get("label") or model_id)
            if provider and provider not in label:
                where = {
                    "ollama-cloud": "Ollama Cloud",
                    "ollama-local": "Ollama Local",
                    "local": "on-device",
                    "mlx": "on-device",
                    "in-process": "on-device",
                    "lmstudio": "LM Studio",
                }.get(provider, provider)
                label = f"{model_id} · {where}"
            models.append({
                "id": model_id,
                "label": label,
                "location": location,
                "provider": provider,
                "route_provider": route_provider,
                "in_use": bool(row.get("serving")),
                "source": str(row.get("source") or "jaeger"),
                "notes": str(row.get("description") or row.get("status") or ""),
                "context_length": row.get("context_length"),
            })
            if provider:
                providers.setdefault(provider, {
                    "id": provider, "label": provider,
                    "status": "configured", "source": "jaeger",
                })
        active = serving_model() or {}
        active_provider = str(active.get("provider") or "").strip() or None
        if active_provider == "ollama":
            active_provider = (
                "ollama-cloud" if active.get("location") == "cloud" else "ollama-local"
            )
        return {
            "instance": getattr(boot, "instance_name", None),
            "serving": {
                "model": active.get("name"),
                "provider": active_provider,
                "route_provider": active.get("provider"),
                "context_length": active.get("context_length"),
            } if active else {},
            "models": models,
            "providers": list(providers.values()),
        }

    if what == "model_picker":
        # Same two-stage grouping the terminal ``/model`` picker uses, so
        # the windowed overlay is a clickable twin rather than a flat
        # catalogue dumped into the transcript.
        from jaeger_ai.interfaces.tui.slash_commands import picker_catalog
        from jaeger_ai.main import _pipeline

        cfg = _pipeline.get("config")
        if cfg is None and lay is not None:
            try:
                from jaeger_ai.core.instance.schemas import Config, load_yaml
                cfg = load_yaml(lay.config_path, Config)
            except Exception:  # noqa: BLE001
                cfg = None
        return picker_catalog(layout=lay, cfg=cfg)

    if what == "settings_catalog":
        # The schema-derived settings surface — the SAME catalog `jaeger
        # settings` drives. Grouped {group: [descriptor, ...]}; the native
        # app renders each descriptor by type (bool→Toggle, enum→Picker,
        # int/float→field, str→field). No hand-enumerated field list on
        # either side — a new setting is one annotated Field in schemas.py.
        from jaeger_ai.core.settings.catalog import catalog as _catalog
        return _catalog(lay, advanced=bool(args.get("advanced", True)),
                        group=args.get("group"))
    if what == "skill_usage":
        # usage_stats already records every skill view and tool call to
        # <instance>/logs/usage.json; it just had no way out of the runtime,
        # so external surfaces (ARES's skills panel) reported zeros while the
        # real counts sat on disk. Expose the existing snapshot rather than
        # keeping a second tally.
        from jaeger_ai.core.runtime import usage_stats
        snap = usage_stats.snapshot()
        skills = snap.get("skills") or {}
        tools = snap.get("tools") or {}
        return {
            "ok": True,
            "owner": "jaeger",
            "usage_available": True,
            "skills": skills,
            "tools": tools,
            "total_skill_views": sum(
                int(v.get("views") or 0) for v in skills.values() if isinstance(v, dict)
            ),
            "unique_skills_used": len(skills),
            "top_skills": usage_stats.top_skills(10),
            "top_tools": usage_stats.top_tools(10),
        }
    if what == "permissions":
        from jaeger_os.core.safety.permissions import PermissionGrants

        from jaeger_ai.core.instance.schemas import Config, load_yaml
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
        from jaeger_ai.core.instance.setup_wizard import setup_defaults
        return setup_defaults()
    if what == "list_sessions":
        # Runway item 4 (0.8): the native History surface's row list —
        # id/title/preview/created_at/last_active/messages, most-active
        # first. Works pre-boot (the store is layout-keyed, not agent-
        # keyed) so History can populate while the model is still warming.
        from jaeger_ai.core.sessions import get_store
        store = get_store(lay)
        if store is None:
            return []
        return _stamp_cron_running(
            store.list_sessions(limit=int(args.get("limit") or 50)))
    if what == "session_contract":
        return _session_contract()
    if what == "search_sessions":
        from jaeger_ai.core.sessions import get_store
        store = get_store(lay)
        if store is None:
            return []
        return store.search(
            str(args.get("query") or ""), limit=int(args.get("limit") or 50)
        )
    if what == "load_session":
        # resume False: display/search only — do not swap the live agent.
        # resume omitted/True: replay into JaegerAgent.messages so the next
        # send on this id continues with those turns.
        from jaeger_ai.core.sessions import canonical_session_id
        from jaeger_ai.main import resume_session_from_store
        raw_sid = str(args.get("id") or "").strip()
        if not raw_sid:
            return []
        sid = canonical_session_id(raw_sid)
        if args.get("resume") is False:
            from jaeger_ai.core.sessions import get_store

            store = get_store(lay)
            return store.history(sid) if store is not None else []
        return resume_session_from_store(
            getattr(boot, "client", None), sid, layout=lay)
    if what == "check_update":
        # In-app updates (0.8): {current, latest, available, notes_url}.
        # Cached under <instance>/run/update_check.json for ~24h — see
        # version_check.cached_update_status — so app-launch + periodic
        # tray polling doesn't hammer the GitHub API. Works pre-boot
        # (layout-keyed cache, no client needed).
        from jaeger_ai.core.version_check import cached_update_status
        return cached_update_status(lay)
    if what == "list_runs":
        return _runtime_query_runs(args)
    if what == "list_commitments":
        return _runtime_query_commitments(args)
    if what == "list_effects":
        return _runtime_query_effects(args)
    return None


def _apply_live_character() -> None:
    """Rebuild the running agent's prompt + drop in-memory history so a
    HUD pick takes effect this process, not on the next restart."""
    try:
        from jaeger_ai.main import apply_live_character
        apply_live_character()
    except Exception:  # noqa: BLE001 — bind already landed; live apply is best-effort
        pass


def _command(cmd: str, args: dict[str, Any], boot: Any) -> tuple[bool, str | None]:
    """Mutations for the settings HUD — each forwards to a tested function."""
    root = _instance_root(boot)
    lay = getattr(boot, "layout", None)
    try:
        import jaeger_ai.personality.character as ch
        if cmd == "select_character":
            # Live override only. Binding (manifest.bound_character) is
            # make_default — an explicit rebind, not a side effect of the pick.
            ch.set_active_character(root, args["id"])
            _apply_live_character(); return True, None
        if cmd == "make_default":
            ch.bind_character(root, args["id"])
            _apply_live_character(); return True, None
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
            from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml
            cfg = load_yaml(lay.config_path, Config)
            _apply_config(cfg, args)
            dump_yaml(lay.config_path, Config.model_validate(cfg.model_dump()))
            return True, None
        if cmd == "save_identity":
            # Instance-owned identity: the agent's NAME and profile PICTURE
            # (never the character). An avatar source path is copied INTO the
            # instance dir so the picture travels with the instance; a
            # falsy/empty avatar clears it (→ fall back to the character card).
            import shutil
            from pathlib import Path

            from jaeger_ai.core.instance.schemas import Identity, dump_yaml, load_yaml
            data = load_yaml(lay.identity_path, Identity).model_dump()
            name = str(args.get("name") or "").strip()
            if name:
                data["name"] = name
            if "avatar" in args:
                src = args.get("avatar")
                srcp = Path(str(src)).expanduser() if src else None
                if srcp is not None and srcp.is_file():
                    dst = Path(lay.root) / f"avatar{srcp.suffix.lower() or '.png'}"
                    shutil.copy2(srcp, dst)
                    data["avatar"] = dst.name          # relative to the instance
                else:
                    data["avatar"] = None              # cleared → character card
            dump_yaml(lay.identity_path, Identity.model_validate(data))
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
                    from jaeger_agent.tools.speak import speak
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
        if cmd == "create_schedule":
            from jaeger_ai.core.runtime.schedules import create_job

            create_job(
                prompt=str(args.get("prompt") or ""),
                schedule=str(args.get("schedule") or args.get("cron") or ""),
                name=args.get("name") or args.get("id"),
                at=args.get("at"),
                deliver=args.get("deliver"),
                recipient=args.get("recipient"),
            )
            return True, None
        if cmd == "cancel_schedule":
            from jaeger_ai.core.runtime.schedules import cancel_job

            result = cancel_job(str(args.get("name") or args.get("id") or ""))
            return bool(result.get("cancelled")), (
                None if result.get("cancelled") else "schedule not found"
            )
        if cmd == "pause_schedule":
            from jaeger_ai.core.runtime.schedules import pause_job

            result = pause_job(str(args.get("name") or args.get("id") or ""))
            return bool(result.get("paused")), (
                None if result.get("paused") else "schedule not found"
            )
        if cmd == "resume_schedule":
            from jaeger_ai.core.runtime.schedules import resume_job

            result = resume_job(str(args.get("name") or args.get("id") or ""))
            return bool(result.get("resumed")), (
                None if result.get("resumed") else "schedule not found"
            )
        if cmd == "deliver_event":
            return _runtime_deliver_event(str(args.get("wake_key") or args.get("key") or ""))
        if cmd == "resolve_effect":
            return _runtime_resolve_effect(str(args.get("key") or ""), args.get("result"))
        if cmd == "abandon_effect":
            return _runtime_abandon_effect(str(args.get("key") or ""))
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
        "heartbeat_enabled": ("heartbeat", "enabled"),
        "heartbeat_interval_minutes": ("heartbeat", "interval_minutes"),
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
        self.supervisor_stop: Any = None      # idle/heartbeat thread Event
        self.bridge_sock: Any = None
        self.webhook_httpd: Any = None
        self.last_user_at = time.monotonic()
        self.last_user_session = "desktop-app"
        # True while ANY turn (chat, slash, or a fired cron prompt) is
        # running — the cheap "is a turn in flight?" signal run_update's
        # guard reads before shelling out (an update mid-turn would race
        # the turn's file reads against the swap). Mirrors the state
        # frames' busy flag; kept on ctx too since state frames are
        # fire-and-forget, not queryable.
        self.busy = False
        self.boot_error: str | None = None
        self.booted = threading.Event()      # set on success OR failure
        # ── one instance → at most one authoritative bridge ───────────
        # Set when this process has established it is NOT the instance's
        # runtime owner (it lost the flock). Such a bridge has no agent and
        # never will: it must neither linger (~75 MB each; 12 orphans were
        # found resident) nor own the attach socket. ``inbound`` is parked
        # here so the boot thread — which discovers the loss — can push the
        # shutdown sentinel into the main loop it does not otherwise see.
        self.exit_requested = threading.Event()
        self.inbound: Any = None
        # Pending permission requests: id → (event, answer-slot). An answer
        # that arrives before the request is registered (pipelined client,
        # tests) parks in ``early`` and resolves on registration.
        self.pending: dict[str, tuple[threading.Event, list[str]]] = {}
        self.early: dict[str, str] = {}
        self.req_counter = 0
        # 0.8.1 item 9: session → count of sends queued (received while
        # ``busy`` was True) but not yet picked up by the turn worker.
        # Purely a telemetry counter for the ``queued`` ack frame — the
        # actual queueing/ordering guarantee comes from ``turns`` being a
        # plain FIFO ``queue.Queue`` drained by one worker thread, which
        # already ran every send as a normal turn before this existed.
        self.session_pending: dict[str, int] = {}
        # JaegerAgent's workspace binding is process-global. Serialize every
        # bridge/cron turn while a per-request ARES workspace is installed.
        self.workspace_lock = threading.RLock()


@contextmanager
def _turn_workspace(ctx: _Ctx, requested: Any):
    """Temporarily bind file tools to the validated ARES session workspace."""
    from jaeger_agent import tools as jaeger_tools

    from jaeger_ai.main import _pipeline

    raw = str(requested or "").strip()
    candidate: Path | None = None
    if raw:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise ValueError("bridge workspace must be an absolute path")
        candidate = candidate.resolve()
        if not candidate.is_dir():
            raise ValueError(f"bridge workspace does not exist: {candidate}")
    with ctx.workspace_lock:
        config = _pipeline.get("config")
        configured = getattr(getattr(config, "workspace", None), "location", None)
        # TWO bindings, deliberately:
        #
        #   workspace_override — where ``workspace/...`` writes are filed.
        #   project_root       — the directory the agent is working IN.
        #
        # Only the first existed before, so an ARES workspace switch moved a
        # value no tool consumed: run_shell still ran in a tempdir, relative
        # reads still resolved against the launch directory, and a default
        # search still scanned the instance's skills dir. Binding the project
        # root is what makes the selector mean something.
        jaeger_tools.bind(
            ctx.layout,
            workspace_override=candidate or configured,
            project_root=candidate,
        )
        try:
            yield
        finally:
            jaeger_tools.bind(ctx.layout, workspace_override=configured)


class BridgeConfirmationProvider:
    """Interactive tier-2+ approval over the NDJSON wire — the headless
    confirmation surface for a bridge/GUI session (0.9.3 Task 1).

    Emits a ``request`` frame (``kind="approval"``, ``options=("once",
    "always", "deny")``) and BLOCKS the TURN thread — stdin stays free, so
    ``respond``/``quit`` keep working — until a matching
    ``{"op":"respond","id":…,"answer":…}`` arrives. Timeout (120s) or a
    dead client denies, fail-safe, same as the console provider's
    non-tty path.

    Grants are the SAME store :class:`~jaeger_os.core.safety.permissions.
    ConsoleConfirmationProvider` reads/writes — ``<instance>/
    permissions.json`` — so an "always" answered here (or at the console,
    or on a prior boot) is visible everywhere and SKIPS THE FRAME
    ENTIRELY on the next tier-2 call for that skill; no round trip, no
    UI. ``once`` approves only the call in flight and records nothing —
    the very next call on that skill prompts again (unlike the console's
    session-scoped "yes"; the bridge dialog only distinguishes
    call-scoped vs. permanent).

    Provider selection lives in two places by design, not one:
    ``main._confirmation_provider`` picks Console (tty prompt, unchanged)
    or ``AllowAllProvider`` (operator's "allow" mode / --yes) at BOOT,
    before anyone knows whether this process is a bridge child; then
    ``_boot_agent`` (below) swaps Console for THIS class once it's clear
    we're serving a Swift/bridge session — UNLESS the boot-time choice
    was ``AllowAllProvider``, which is left alone so --yes/"allow" mode
    behaves identically everywhere. A tty-less, bridge-less process (an
    MCP server, a cron-only headless daemon) never reaches this swap, so
    it keeps Console's fail-closed non-tty behavior — the same
    fail-closed default as always.
    """

    TIMEOUT_S = 120.0

    def __init__(self, proto: TextIO, ctx: _Ctx) -> None:
        self._proto = proto
        self._ctx = ctx
        from jaeger_os.core.safety.permissions import PermissionGrants
        root = getattr(getattr(ctx, "layout", None), "root", None)
        self._grants = PermissionGrants.load(root)

    def bind_output(self, proto: TextIO) -> None:
        """Route the next turn's prompts to the client that sent the turn.

        The bridge has one turn worker but can have several transports: its
        owner stdio pipe and any number of attached Unix-socket clients.  A
        provider permanently bound at boot sends an attached client's
        approval request to the owner, leaving the initiating client blocked
        forever.  Turns are serialized, so rebinding at the turn boundary is
        sufficient and cannot cross-talk between simultaneous tool calls.
        """
        self._proto = proto

    def request(self, kind: str, prompt: str,
                options: tuple[str, ...] = ()) -> str:
        """Emit one interactive request and block for its matching answer."""
        from jaeger_os.contract import protocol

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
            rid, kind, prompt, options=options,
            session=str(getattr(self, "current_session", "") or "")))
        try:
            if not evt.wait(self.TIMEOUT_S):
                return ""
            return (slot[0] if slot else "").strip()
        finally:
            self._ctx.pending.pop(rid, None)

    def confirm(self, request: object) -> bool:
        skill = getattr(request, "skill", "") or ""
        if self._grants.is_granted(skill):
            return True  # already approved (console "always", or ours) — no frame
        op = f"{skill}.{getattr(request, 'operation', '') or 'this action'}"
        answer = self.request(
            "approval", f"Allow {op}?", ("once", "always", "deny"),
        ).lower()
        if answer == "always":
            self._grants.grant_persistent(skill)
            return True
        return answer in ("once", "allow", "yes", "y", "true", "1", "approve")


def _request_exit(ctx: _Ctx) -> None:
    """Ask the main loop to shut down, from a thread that cannot reach it.

    The boot thread starts before ``inbound`` exists, so it may discover the
    lock loss either side of that. Setting the event covers the early case
    (``main`` re-checks it as soon as the queue exists) and pushing the
    sentinel covers the late one. Both are idempotent — the loop stops at the
    first ``None`` and ignores the rest.
    """
    ctx.exit_requested.set()
    queue = ctx.inbound
    if queue is not None:
        try:
            queue.put(None)
        except Exception:  # noqa: BLE001 — teardown must never raise
            pass


def _boot_agent(proto: TextIO, ctx: _Ctx, instance: str) -> None:
    """Background boot: load the model, wire tool/permission forwarding,
    then stream the ``agent_state`` transition. Never raises."""
    from jaeger_os.contract import protocol
    try:
        from jaeger_ai.main import boot_for_tui
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
        if kind == "locked":
            # We lost the instance flock, so another process IS this
            # instance's runtime. This one has no agent and never will.
            #
            # It used to stay resident anyway — the transport kept serving,
            # so it sat at ~75 MB advertising an agent it did not have, and
            # (worse) it had already replaced the OWNER's attach socket,
            # since ``bsock.bind`` unlinks whatever file is in its way. Every
            # client that attached after that reached this brain-less process,
            # gave up, and spawned another bridge — which lost the lock and
            # hijacked the socket in turn. That is the spawn burst and the
            # orphan pile in one mechanism.
            #
            # Losing the lock is now terminal: emit the fatal frame (the
            # client needs it to go attach to the real owner) and leave.
            _request_exit(ctx)
        return

    ctx.boot = boot
    ctx.client = boot.client
    if os.environ.get("JAEGER_TEST_LOCK_ONLY") == "1":
        ctx.booted.set()
        return

    # First boot on this machine: trigger every TCC prompt now (macOS
    # can't grant in install.sh — grants attach to THIS app identity),
    # so tools don't hit permission walls mid-task. Marker-guarded,
    # never re-prompts, never blocks boot.
    try:
        from jaeger_ai.core.diagnostics.tcc_permissions import first_boot_preflight
        first_boot_preflight()
    except Exception:  # noqa: BLE001
        pass

    # Forward the agent loop's live tool activity as ``tool`` frames.
    class _ToolEmitter:
        def publish(self, event: str, **payload: object) -> None:
            if event == "tool.progress":
                frame = protocol.tool_frame(
                    str(payload.get("name", "")),
                    str(payload.get("phase", "start")),
                    float(payload.get("elapsed_s") or 0.0),
                    detail=str(payload.get("detail", "")))
                if isinstance(payload.get("args"), dict):
                    frame["args"] = payload["args"]
                _emit(proto, frame)

    try:
        from jaeger_ai.main import _pipeline
        _pipeline["event_bus"] = _ToolEmitter()
    except Exception:  # noqa: BLE001
        pass

    # Interactive permission approval over the wire (deny on timeout).
    try:
        from jaeger_os.core.safety.permissions import AllowAllProvider, current_policy
        policy = current_policy()
        if not isinstance(policy.confirmation, AllowAllProvider):
            policy.confirmation = BridgeConfirmationProvider(proto, ctx)
    except Exception:  # noqa: BLE001
        pass

    # Prefix-exact KV prewarm for the app's chat session, BEFORE the
    # ready frame — the splash holds on agent_state "ready", so by the
    # time the operator can type, the first turn's whole prompt prefix
    # (session system prompt + tool schemas + resume digest) is already
    # prefilled and message #1 starts decoding immediately.
    try:
        from jaeger_ai.main import prewarm_session
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
        job_name = _cron_job_name(session)
        _mark_cron_running(job_name)
        try:
            _emit_state(proto, ctx, True, session)
            try:
                from jaeger_ai.main import run_for_voice
                with ctx.workspace_lock:
                    result = run_for_voice(ctx.client, prompt, session_key=session)
                text = result.get("text") or ""
                _emit(proto, protocol.reply_frame(
                    text, result.get("error"), session,
                    elapsed_s=result.get("elapsed_s"),
                    halt_reason=result.get("halt_reason")))
                try:
                    from jaeger_ai.core.runtime.cron_delivery import deliver_text
                    sent = deliver_text(ctx.layout, job_name, text)
                    if sent and not sent.get("sent"):
                        print(f"[bridge] cron deliver skipped: {sent.get('error')}",
                              file=sys.stderr, flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"[bridge] cron deliver failed: {exc}",
                          file=sys.stderr, flush=True)
                # Speak a fired reminder when the instance voices its
                # replies and the turn didn't already speak via a tool.
                if text and not result.get("spoke_via_tool"):
                    try:
                        from jaeger_ai.main import _pipeline
                        cfg = _pipeline.get("config")
                        if cfg is not None and cfg.voice.speak_replies:
                            from jaeger_agent.tools.speak import speak
                            speak(text=text)
                    except Exception as exc:  # noqa: BLE001 — TTS is best-effort
                        print(f"[bridge] cron speak failed: {exc}",
                              file=sys.stderr, flush=True)
            finally:
                _emit_state(proto, ctx, False, session)
        except Exception as exc:  # noqa: BLE001 — a fired turn must never kill the bridge
            print(f"[bridge] cron turn failed: {exc}",
                  file=sys.stderr, flush=True)
        finally:
            _mark_cron_done(job_name)

    try:
        from jaeger_agent.background.cron_runner import CronRunner
        ctx.cron = CronRunner(_cron_cb, llm_lock=None)
        ctx.cron.start()
    except Exception as exc:  # noqa: BLE001 — no cron is degraded, not fatal
        print(f"[bridge] cron runner skipped: {exc}",
              file=sys.stderr, flush=True)

    try:
        _start_idle_supervisor(proto, ctx)
    except Exception as exc:  # noqa: BLE001 — no idle loop is degraded, not fatal
        print(f"[bridge] idle supervisor skipped: {exc}",
              file=sys.stderr, flush=True)

    try:
        from jaeger_ai.main import _pipeline, autostart_plugins
        autostart_plugins(_pipeline.get("config"))
    except Exception as exc:  # noqa: BLE001
        print(f"[bridge] plugin autostart skipped: {exc}",
              file=sys.stderr, flush=True)

    try:
        _start_webhooks(ctx)
    except Exception as exc:  # noqa: BLE001
        print(f"[bridge] webhooks skipped: {exc}",
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
# frames; anything conversational (goal / deepthink dialogs) and anything
# needing the live TUI (reboot, instance hot-switch) stays TUI-only.
# ``/model`` / ``/models`` are intercepted by the windowed chat and open a
# clickable picker; if they still arrive here we refuse a catalogue dump
# into the transcript. ``/model use …`` is a typed switch and is allowed.
_SLASH_SAFE = ("help", "tools", "skills", "facts", "plugins",
               "instance", "instances", "board", "config",
               "auto", "mode")


def _slash_parts(text: str) -> tuple[str, str]:
    """``("/goal improve notes",)`` → ``("goal", "improve notes")``."""
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return "", ""
    parts = raw.lstrip("/").split(None, 1)
    name = (parts[0] if parts else "").lower()
    rest = parts[1].strip() if len(parts) > 1 else ""
    return name, rest


def _goal_turn_text(text: str) -> str | None:
    """Windowed ``/goal <job>`` is a real agent turn, not a TUI dialog.

    The Swift palette lists /goal; without this rewrite the bridge used
    to bounce it as "needs the terminal TUI" and the job never started.
    """
    name, rest = _slash_parts(text)
    if name == "goal" and rest:
        return rest
    return None


def _windowed_control_slash(text: str) -> str | None:
    """Local replies for /stop /steer /goal (bare). None → TUI dispatch.

    ``/auto`` and ``/mode`` dispatch through the TUI slash registry so
    the windowed composer actually switches execution mode.
    """
    name, rest = _slash_parts(text)
    if name == "stop":
        try:
            from jaeger_ai.main import request_turn_cancel
            request_turn_cancel()
        except Exception:  # noqa: BLE001 — cancel is best-effort
            pass
        return "Stop requested."
    if name == "steer":
        if not rest:
            return "Usage: /steer <guidance for the in-flight run>"
        try:
            from jaeger_ai.main import steer_active_turn
            steer_active_turn(rest)
        except Exception:  # noqa: BLE001
            pass
        return f"Steered: {rest}"
    if name == "goal" and not rest:
        return (
            "Usage: /goal <what to finish>. Example: /goal improve Apple "
            "Notes structure and quality"
        )
    return None


def _run_slash(text: str, ctx: _Ctx) -> str:
    """Dispatch one slash line through the TUI's registry and return the
    rendered output as plain text. Python stays the single source of truth
    for slash behaviour — the client just displays what comes back."""
    from rich.console import Console

    from jaeger_ai.interfaces.tui import slash_commands as sc

    parts = text.lstrip("/").split(None, 1)
    name = (parts[0] if parts else "").lower()
    rest = parts[1] if len(parts) > 1 else ""
    rest_head = (rest.split()[:1] or [""])[0].lower()
    known = name in sc._BY_NAME
    # Bare /model and /models open a clickable overlay in the app. Never
    # print the catalogue into the chat — that's the bug this exists to
    # close. Typed ``/model use …`` is a direct switch and may run here.
    if name in ("model", "models") and rest_head != "use":
        return (
            "The model picker is a clickable overlay — type /model with "
            "no arguments.\nDirect switch:  /model use ollama-cloud <model>"
            "  ·  /model use local <name>  ·  /model use ollama <name>"
            "  ·  /model use mlx <name>"
        )
    if known and name not in _SLASH_SAFE and not (
            name == "model" and rest_head == "use"):
        return (f"/{name} needs the terminal TUI — it isn't available over "
                "the app bridge.\nAvailable here: "
                + "  ".join("/" + n for n in _SLASH_SAFE)
                + "  /model")
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
    ``(used, max)`` tokens, or Nones when unavailable.

    Both numbers come from the same source the TUI gauge and the
    ContextGuard use: ``last_ctx_snapshot`` (prompt estimate vs the
    *serving* window). Falling back to leftover local ``model.ctx``
    is how a 1M Ollama Cloud model rendered as 131K in the Swift bar.
    """
    used = mx = None
    try:
        from jaeger_ai.main import _context_budget_for, _pipeline, last_ctx_snapshot
        snap = last_ctx_snapshot(session)
        if snap:
            used = int(snap.get("tokens") or 0) or None
            mx = int(snap.get("max") or 0) or None
        if mx is None:
            loaded = int(getattr(_pipeline.get("client"), "loaded_ctx", 0) or 0)
            if loaded > 0:
                mx = loaded
            else:
                budgeted, _reserve = _context_budget_for(_pipeline.get("config"))
                mx = int(budgeted or 0) or None
    except Exception:  # noqa: BLE001 — telemetry never breaks a reply
        pass
    return used, mx


_SYNTHETIC_SESSIONS = frozenset({
    "heartbeat", "kanban_idle", "cron", "completions", "worker",
})


def _heartbeat_config(ctx: _Ctx) -> tuple[bool, int, str]:
    enabled, interval, session = True, 30, "heartbeat"
    try:
        from jaeger_ai.core.instance.schemas import Config, load_yaml
        from jaeger_ai.main import _pipeline
        cfg = _pipeline.get("config")
        if cfg is None and ctx.layout is not None:
            cfg = load_yaml(ctx.layout.config_path, Config)
        if cfg is not None:
            hb = cfg.heartbeat
            enabled = bool(hb.enabled)
            interval = int(hb.interval_minutes)
            session = str(hb.session or "heartbeat")
    except Exception:  # noqa: BLE001
        pass
    return enabled, interval, session


def _idle_once(proto: TextIO, ctx: _Ctx) -> None:
    """One supervisor tick. Never raises into the poll loop."""
    from jaeger_agent.background.board import has_actionable_work
    from jaeger_agent.prompts import AUTO_BOARD_PROMPT
    from jaeger_os.contract import protocol

    from jaeger_ai.core.runtime import heartbeat as hb
    from jaeger_ai.core.runtime.completions import next_completion_turn, pending_count
    from jaeger_ai.core.runtime.idle_supervisor import Action, decide, window_elapsed
    from jaeger_ai.core.runtime.task_liveness import reclaim_stale
    from jaeger_ai.main import _pipeline, _run_turn, run_for_voice

    layout = ctx.layout
    if layout is None or ctx.client is None or ctx.busy:
        return
    try:
        reclaim_stale(layout)
    except Exception:  # noqa: BLE001
        pass

    enabled, interval, hb_session = _heartbeat_config(ctx)
    idle_minutes = 30
    try:
        cfg = _pipeline.get("config")
        if cfg is not None:
            idle_minutes = int(cfg.deep_think.auto_idle_minutes)
    except Exception:  # noqa: BLE001
        idle_minutes = 30
    has_dt = False
    try:
        from jaeger_agent.background.deep_think import queue_for_layout
        has_dt = queue_for_layout(layout).next_pending() is not None
    except Exception:  # noqa: BLE001
        has_dt = False

    action = decide(
        busy=ctx.busy,
        has_completions=pending_count() > 0,
        idle_ready=window_elapsed(
            idle_minutes * 60,
            quiet_for=time.monotonic() - ctx.last_user_at,
        ),
        has_deep_think=has_dt,
        has_board=has_actionable_work(layout),
        heartbeat_due=hb.is_due(
            layout, interval_minutes=interval, enabled=enabled,
        ),
    )
    if action is Action.SKIP or action is Action.IDLE:
        return
    if action is Action.DEEP_THINK:
        # Model swap for Deep Think stays on the TUI / --daemon path.
        # The ARES-kept bridge works the board and the standing heartbeat
        # without swapping the live conversational brain.
        action = Action.BOARD if has_actionable_work(layout) else (
            Action.HEARTBEAT if hb.is_due(
                layout, interval_minutes=interval, enabled=enabled,
            ) else Action.IDLE
        )
        if action is Action.IDLE:
            return

    session = ctx.last_user_session or "desktop-app"
    persona = True
    prompt = None
    if action is Action.COMPLETION:
        prompt = next_completion_turn(layout)
        session = ctx.last_user_session or "completions"
    elif action is Action.BOARD:
        prompt = AUTO_BOARD_PROMPT
        session = "kanban_idle"
        persona = False
    elif action is Action.HEARTBEAT:
        prompt = hb.build_prompt(layout)
        session = hb_session
        persona = False
    if not prompt:
        return

    _emit_state(proto, ctx, True, session)
    try:
        if persona:
            result = run_for_voice(ctx.client, prompt, session_key=session)
        else:
            result = _run_turn(
                ctx.client, prompt, session_key=session, allow_persona=False,
            )
        text = result.get("text") or ""
        error = result.get("error")
        if action is Action.HEARTBEAT:
            silent = hb.is_silent_ok(text)
            hb.mark_beat(layout, silent=silent)
            if silent and not error:
                return
        _emit(proto, protocol.reply_frame(
            text, error, session, elapsed_s=result.get("elapsed_s"),
            halt_reason=result.get("halt_reason")))
    finally:
        _emit_state(proto, ctx, False, session)


def _start_idle_supervisor(proto: TextIO, ctx: _Ctx) -> None:
    """Poll for completions, board work, and standing heartbeats."""
    stop = threading.Event()
    ctx.supervisor_stop = stop

    def _loop() -> None:
        while not stop.wait(2.0):
            if not ctx.booted.is_set() or ctx.client is None:
                continue
            try:
                _idle_once(proto, ctx)
            except Exception as exc:  # noqa: BLE001
                print(f"[bridge] idle supervisor: {exc}",
                      file=sys.stderr, flush=True)

    threading.Thread(
        target=_loop, name="idle-supervisor", daemon=True,
    ).start()


def _turn_worker(proto: TextIO, ctx: _Ctx,
                 turns: _queue.Queue[dict[str, Any] | None]) -> None:
    """Runs chat turns off the stdin thread. Blocks each turn on boot
    completion — old clients that chat right after ``ready`` just wait,
    exactly as they did when ``ready`` meant model-loaded."""
    from jaeger_os.contract import protocol
    while True:
        req = turns.get()
        if req is None:
            return
        out = req.pop("_out", None) or proto
        text, prompt_error = _request_text(req)
        from jaeger_ai.core.runtime.dispatch import normalize_session_key
        session = normalize_session_key(
            req.get("session"), default="desktop-app",
        )
        if prompt_error:
            _emit(out, protocol.reply_frame("", prompt_error, session))
            continue
        if session not in _SYNTHETIC_SESSIONS:
            ctx.last_user_at = time.monotonic()
            ctx.last_user_session = session
        # This request is no longer "waiting" — it's about to run. Mirrors
        # the increment in ``main``'s stdin loop (item 9's queued-ack
        # counter); covers both the slash and chat branches below since
        # either can have been queued mid-turn.
        pending = ctx.session_pending.get(session)
        if pending:
            ctx.session_pending[session] = max(0, pending - 1)
        # Slash pre-dispatch — same contract as the TUI REPL: a leading
        # ``/`` is a command, never a prompt for the model. Runs before
        # the boot wait so ``/help`` answers even while the model loads.
        # Exception: ``/goal <job>`` is rewritten into a real turn so the
        # windowed palette actually starts the autonomous loop.
        goal_text = _goal_turn_text(text)
        if text.startswith("/") and goal_text is None:
            _emit_state(out, ctx, True, session)
            try:
                reply = _windowed_control_slash(text) or _run_slash(text, ctx)
                _emit(out, protocol.reply_frame(reply, None, session))
            except Exception as exc:  # noqa: BLE001 — a bad command must not kill the bridge
                _emit(out, protocol.reply_frame("", str(exc), session))
            finally:
                _emit_state(out, ctx, False, session)
            continue
        if goal_text is not None:
            text = goal_text
        ctx.booted.wait()
        if ctx.client is None:
            _emit(out, protocol.reply_frame(
                "", ctx.boot_error or "agent failed to boot", session))
            continue
        # Approval requests must return on the same transport that originated
        # this turn.  The provider is installed during boot on owner stdio,
        # while ``out`` may be an attached Unix-socket client.
        try:
            from jaeger_os.core.safety.permissions import current_policy

            confirmation = current_policy().confirmation
            if isinstance(confirmation, BridgeConfirmationProvider):
                confirmation.bind_output(out)
        except Exception:  # noqa: BLE001 — routing must not block a turn
            pass
        try:
            from jaeger_ai.core.sessions import get_store

            store = get_store(ctx.layout)
            if store is not None:
                store.create(
                    session,
                    origin=req.get("source") or req.get("origin"),
                )
                store.set_execution_state(session, "running")
        except Exception:  # noqa: BLE001 — state telemetry cannot fail a turn
            pass
        _emit_state(out, ctx, True, session)
        try:
            from jaeger_ai.core.runtime import continuation, execution
            from jaeger_ai.core.runtime.autonomous_runner import (
                ledger_open,
                next_continuation_prompt,
            )
            from jaeger_ai.main import (
                interaction_request_sink,
                run_for_voice,
                stream_delta_sink,
                stream_reasoning_sink,
            )

            current_prompt = text
            max_continuations = execution.max_steps()
            step = 0
            accumulated_text: list[str] = []
            result: dict[str, Any] = {}

            while True:
                deltas = _DeltaStream(out, session)
                with _turn_workspace(ctx, req.get("workspace")):
                    display_text = req.get("display_text") if step == 0 else None
                    voice_kwargs: dict[str, Any] = {"session_key": session}
                    if display_text is not None:
                        voice_kwargs["display_text"] = str(display_text)
                    def _emit_reasoning(chunk: str, _session: str = session) -> None:
                        # Deliberation is emitted as its own frame, not folded
                        # into the delta stream: it is NOT part of the answer,
                        # and a client appending it to the visible text would
                        # render the model's internal monologue as the reply.
                        deltas.flush()
                        _emit(out, _reasoning_frame(chunk, _session))

                    def _request_interaction(
                        kind: str, prompt: str, options: tuple[str, ...],
                    ) -> str:
                        from jaeger_os.core.safety.permissions import current_policy

                        provider = current_policy().confirmation
                        if isinstance(provider, BridgeConfirmationProvider):
                            return provider.request(kind, prompt, options)
                        return ""

                    with (
                        stream_delta_sink(deltas.feed),
                        stream_reasoning_sink(_emit_reasoning),
                        interaction_request_sink(_request_interaction),
                    ):
                        result = run_for_voice(ctx.client, current_prompt, **voice_kwargs)
                deltas.flush()

                ans = (result.get("text") or "").strip()
                if ans:
                    accumulated_text.append(ans)

                if result.get("error") or execution.stop_requested():
                    break

                # Inner-cap halt is "start the next step", not "stop".
                # Loop-breaker halt (identical/timeout spam) IS a stop.
                nxt_prompt = None
                halt = result.get("halt_reason")
                if continuation.is_loop_breaker(halt):
                    break
                if ledger_open() or continuation.hit_inner_cap(halt):
                    nxt_prompt = next_continuation_prompt(
                        ans, force_ledger=ledger_open(),
                        halt_reason=halt,
                    )
                elif continuation.enabled() and step < max_continuations:
                    verdict = continuation.classify(ans)
                    if verdict == "continue":
                        nxt_prompt = continuation.continuation_prompt()

                if nxt_prompt and step < max_continuations:
                    step += 1
                    current_prompt = nxt_prompt
                    continue
                else:
                    break

            final_text = "\n\n".join(accumulated_text) if accumulated_text else (result.get("text") or "")
            used, mx = _ctx_usage(session)
            _emit(out, protocol.reply_frame(
                final_text, result.get("error"), session,
                elapsed_s=result.get("elapsed_s"),
                ctx_used=used, ctx_max=mx,
                halt_reason=result.get("halt_reason")))
        except Exception as exc:  # noqa: BLE001 — a bad turn must not kill the bridge
            _emit(out, protocol.reply_frame("", str(exc), session))
        finally:
            try:
                from jaeger_ai.core.sessions import get_store

                store = get_store(ctx.layout)
                if store is not None:
                    store.set_execution_state(session, "idle")
            except Exception:  # noqa: BLE001 — state telemetry is best-effort
                pass
            _emit_state(out, ctx, False, session)


def _start_webhooks(ctx: _Ctx) -> None:
    """Loopback HTTP triggers → board card or synthetic turn."""
    from jaeger_ai.core.runtime import webhooks as hooks
    from jaeger_ai.main import _pipeline

    cfg = _pipeline.get("config")
    wcfg = getattr(cfg, "webhooks", None) if cfg is not None else None
    if wcfg is None or not bool(getattr(wcfg, "enabled", True)):
        return
    host = str(getattr(wcfg, "host", None) or hooks.DEFAULT_HOST)
    port = int(getattr(wcfg, "port", None) or hooks.DEFAULT_PORT)
    secret = str(getattr(wcfg, "secret", None) or "")

    def _on_hook(interpreted: dict[str, str]) -> dict[str, Any]:
        action = interpreted.get("action") or "board"
        title = interpreted.get("title") or "webhook"
        prompt = interpreted.get("prompt") or title
        if action == "turn" and ctx.client is not None:
            from jaeger_ai.main import run_worker_turn
            text = run_worker_turn(ctx.client, prompt, session_key="webhook")
            return {"fired": "turn", "text": (text or "")[:500]}
        from jaeger_agent.background.board import board_for_layout
        card = board_for_layout(ctx.layout).add(
            title, description=prompt, column="ready",
            source="schedule", created_by="agent",
        )
        return {"fired": "board", "card_id": card.id}

    httpd = hooks.serve(
        _on_hook, host=host, port=port, secret=secret,
    )
    ctx.webhook_httpd = httpd
    print(f"[bridge] webhooks on {host}:{port}", file=sys.stderr, flush=True)


def _start_bridge_socket(
    ctx: _Ctx,
    inbound: _queue.Queue[tuple[dict[str, Any], Any] | None],
    owner_out: TextIO,
) -> None:
    """Listen on the instance Unix socket so a second UI can attach."""
    from jaeger_os.contract import protocol

    from jaeger_ai.core.runtime import bridge_socket as bsock

    path = bsock.socket_path(ctx.layout)
    if path is None:
        return
    # NEVER take an attach point that is already being served. ``bsock.bind``
    # unlinks whatever file is in its way — which is right for a STALE socket
    # left by a crash, and catastrophic for a LIVE one: it silently moves
    # every future client off the instance's real runtime and onto this
    # process. Probing first is what separates the two cases, and it is the
    # only thing that distinguishes "recovering from a crash" from "hijacking
    # a healthy owner". A losing process exits via the lock check in
    # ``_boot_agent``; it must not damage the winner on its way out.
    # Reached only after this process holds the instance flock, so any file at
    # this path belongs to a dead or dying predecessor. ``bind`` unlinks it,
    # which is what makes crash recovery work; the ownership question is
    # settled by the lock, not by whether the old file still answers.
    live = bsock.try_connect(path, timeout_s=0.4)
    if live is not None:
        bsock.close_quietly(live)
        print(f"[bridge] reclaiming attach socket {path} from a previous "
              "holder — this process owns the instance lock.",
              file=sys.stderr, flush=True)
    sock = bsock.bind(path)
    ctx.bridge_sock = sock
    print(f"[bridge] attach socket {path}", file=sys.stderr, flush=True)

    def _client(conn: Any) -> None:
        f = None
        try:
            f = conn.makefile("rwb", buffering=0)
            text = conn.makefile("rw", buffering=1, encoding="utf-8", newline="\n")
            text._jaeger_attach_stream = True
            _emit(text, protocol.ready_frame(
                getattr(getattr(ctx.layout, "root", None), "name", None) or "default",
                _model_name(ctx.boot) if ctx.boot is not None else None,
                agent="ready" if ctx.client is not None else "booting",
                agent_name=_agent_name(ctx.boot if ctx.boot is not None else ctx),
            ))
            if ctx.client is not None:
                name, icon = _active_character(ctx.boot)
                _emit(text, protocol.agent_state_frame(
                    "ready", model=_model_name(ctx.boot),
                    character=name, icon=icon,
                    agent_name=_agent_name(ctx.boot)))
            for raw in text:
                line = raw.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(parsed, dict):
                    inbound.put((parsed, text))
        except Exception as exc:  # noqa: BLE001
            print(f"[bridge] attach client dropped: {exc}",
                  file=sys.stderr, flush=True)
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            if f is not None:
                try:
                    f.close()
                except Exception:  # noqa: BLE001
                    pass

    def _accept() -> None:
        retryable = {errno.EINTR, errno.EAGAIN, errno.EWOULDBLOCK, errno.ETIMEDOUT}
        while True:
            if ctx.supervisor_stop is not None and ctx.supervisor_stop.is_set():
                break
            try:
                conn, _addr = sock.accept()
            except TimeoutError:
                continue
            except OSError as exc:
                if exc.errno in retryable:
                    continue
                print(f"[bridge] attach accept stopped: {exc}",
                      file=sys.stderr, flush=True)
                break
            threading.Thread(
                target=_client, args=(conn,), name="bridge-attach", daemon=True,
            ).start()

    threading.Thread(target=_accept, name="bridge-socket", daemon=True).start()


def main(argv: list[str] | None = None, *, own_process: bool = False) -> int:
    """Run the bridge protocol loop.

    ``own_process`` says this call owns the interpreter it is running in,
    which is what licenses the ``os._exit`` in the teardown below. The real
    entry point is always a subprocess (``python -m
    jaeger_ai.interfaces.bridge``), so it passes True. In-process callers —
    the test suite, dev/scripts/walk_task1_bridge_confirmation.py — leave it
    False, because there ``os._exit`` would take down a host process that
    has its own work left to do.
    """
    argv = sys.argv[1:] if argv is None else argv

    # This module is also probed by installers and integration inventories.
    # Treat help flags as flags, not as instance names; the old behavior
    # silently created an on-disk instance literally named ``--help``.
    if argv and argv[0] in {"-h", "--help"}:
        print("usage: python -m jaeger_ai.interfaces.bridge [INSTANCE]")
        return 0

    # The protocol stream is the REAL stdout.  Repoint sys.stdout at
    # stderr for the rest of the process so boot logs / stray prints land
    # on stderr and never corrupt the NDJSON the client is parsing.
    proto = sys.stdout
    sys.stdout = sys.stderr

    from jaeger_os.contract import protocol

    from jaeger_ai.core.instance.instance import (
        InstanceLayout,
        default_instance_name,
        resolve_instance_dir,
    )

    instance = (argv[0] if argv else None) or default_instance_name()

    ctx = _Ctx()
    # Cheap layout resolve — queries/commands work from here, no model needed.
    try:
        ctx.layout = InstanceLayout(resolve_instance_dir(instance))
    except Exception:  # noqa: BLE001 — queries will report per-call
        ctx.layout = None

    # PROCESS REGISTRATION: `jaeger status` reads run/jaeger.pid to decide
    # whether a bridge is live. Nothing wrote it before, so status was
    # structurally blind to a running bridge (field blocker #1). Registration
    # is best-effort — an unwritable instance dir must never block boot — but
    # a live owner is authoritative: refuse rather than run two bridges
    # against one instance.
    _pids = ExitStack()
    if ctx.layout is not None:
        try:
            _pids.enter_context(pidfile.acquire(ctx.layout))
        except pidfile.AlreadyRunning as exc:
            # kind="locked" is the established contract for "another process
            # holds this instance" — BridgeProcess.swift maps it to
            # .locked and offers attach-or-pick. A novel kind would
            # fall through to a generic boot error.
            _emit(proto, protocol.fatal_frame(str(exc), kind="locked"))
            return 1
        except Exception as exc:  # noqa: BLE001 — visibility is not a boot gate
            print(f"[bridge] pid registration skipped: {exc}",
                  file=sys.stderr, flush=True)

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
        _emit(proto, protocol.fatal_frame(
            msg, kind="no_instance",
            suggested_name=_suggested_name(instance)))
        ctx.booted.set()
    else:
        _emit(proto, protocol.agent_state_frame("booting"))
        booter = threading.Thread(
            target=_boot_agent, args=(proto, ctx, instance),
            name="bridge-boot", daemon=True)
        booter.start()

    turns: _queue.Queue[dict[str, Any] | None] = _queue.Queue()
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
        from jaeger_ai.core.instance.setup_wizard import create_instance
        cid = str(args.get("character_id") or "").strip()
        if not cid:
            return False, None, "character_id is required"
        try:
            lay = create_instance(
                character_id=cid,
                name=(args.get("name") or None),
                display_name=(args.get("display_name") or None),
                user_name=(args.get("user_name") or None),
                custom_prime_directive=(args.get("custom_prime_directive") or None),
                role=(args.get("role") or None),
                personality=(args.get("personality") or None),
                voice_id=(args.get("voice_id") or None),
                awake_model=(args.get("awake_model") or None),
                asleep_model=(args.get("asleep_model") or None),
                permission_mode=str(args.get("permission_mode") or "confirm"),
                interaction_mode=str(args.get("interaction_mode") or "gui"),
                make_default=bool(args.get("make_default", True)),
            )
        except Exception as exc:  # noqa: BLE001 — reported, never crashes the bridge
            return False, None, str(exc)
        ctx.layout = lay
        return True, {"instance": lay.root.name, "root": str(lay.root)}, None

    owner_out = proto
    inbound: _queue.Queue[tuple[dict[str, Any], Any] | None] = _queue.Queue()
    # Publish the queue so the boot thread can stop us (see ``_request_exit``),
    # then immediately honour a shutdown it may already have requested — the
    # boot thread starts earlier than this line and can lose the lock before
    # there is a queue to push a sentinel into.
    ctx.inbound = inbound
    if ctx.exit_requested.is_set():
        inbound.put(None)

    def _read_stdio() -> None:
        try:
            for raw in sys.stdin:
                line = raw.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(parsed, dict):
                    inbound.put((parsed, owner_out))
        finally:
            inbound.put(None)

    threading.Thread(target=_read_stdio, name="bridge-stdio", daemon=True).start()
    # Publish the attach point only once THIS process is established as the
    # instance's runtime — i.e. after boot has taken the flock.
    #
    # Binding eagerly (before boot) was wrong in both directions. A process
    # that went on to lose the lock had already taken the socket, so clients
    # attached to a bridge with no agent; and a process that DID own the lock
    # would decline to bind if any stale holder still had the path, which is
    # the state found on this machine: an old bridge holding the socket file
    # open while no longer accepting, and the real lock owner sitting there
    # with no attach point at all. "Something is listening" was never the
    # right question — "do we own this instance" is, and the flock already
    # answers it exactly once.
    #
    # Losing the lock is terminal (see ``_boot_agent``), so a process that
    # reaches here booted is by construction the owner and may reclaim the
    # path from a zombie holder.
    def _publish_attach_socket() -> None:
        ctx.booted.wait()
        if ctx.exit_requested.is_set() or ctx.client is None:
            return                      # no agent to attach to; stay unpublished
        try:
            _start_bridge_socket(ctx, inbound, owner_out)
        except Exception as exc:  # noqa: BLE001 — stdio still works alone
            print(f"[bridge] attach socket skipped: {exc}", file=sys.stderr, flush=True)

    threading.Thread(target=_publish_attach_socket,
                     name="bridge-attach-publish", daemon=True).start()

    rc = 0
    try:
        while True:
            item = inbound.get()
            if item is None:
                break
            req, proto = item
            op = req.get("op")
            if op == "quit":
                if proto is owner_out:
                    break
                continue
            if op == "cancel":
                # The stdin thread stays responsive while the turn worker is
                # blocked in inference or a tool. Keep this fire-and-forget so
                # a second client thread can interrupt without competing to
                # read a control acknowledgement from stdout.
                from jaeger_ai.main import request_turn_cancel
                request_turn_cancel()
                continue
            if op == "steer":
                # Steering is likewise delivered directly to the active agent
                # instead of waiting behind the queued turn.
                from jaeger_ai.main import steer_active_turn
                steer_active_turn(str(req.get("text") or ""))
                continue
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
            if op == "command" and (req.get("cmd") or "") in {
                "clone_skill", "install_skill", "enable_skill",
                "disable_skill", "remove_skill",
            }:
                a = req.get("args") or {}
                cmd = str(req.get("cmd") or "")
                try:
                    from jaeger_ai.core.skills import service as skill_service

                    if ctx.layout is None:
                        raise skill_service.SkillServiceError("no Jaeger instance is selected")
                    if cmd == "clone_skill":
                        data = skill_service.clone_skill(ctx.layout, a.get("name"))
                    elif cmd == "install_skill":
                        data = skill_service.install_skill(
                            ctx.layout, a.get("name"), a.get("content"), a.get("category") or "")
                    elif cmd in {"enable_skill", "disable_skill"}:
                        data = skill_service.set_skill_enabled(
                            ctx.layout, a.get("name"), cmd == "enable_skill")
                    else:
                        data = skill_service.remove_skill(ctx.layout, a.get("name"))
                    _emit(proto, protocol.result_frame(req.get("id"), data=data, ok=True))
                except Exception as exc:  # noqa: BLE001 — report through the contract
                    _emit(proto, protocol.result_frame(
                        req.get("id"), ok=False, error=str(exc)))
                continue
            if op == "command" and (req.get("cmd") or "") in {
                "create_session", "clear_session", "delete_session",
                "reconcile_session_transcript",
            }:
                try:
                    from jaeger_ai.core.sessions import canonical_session_id, get_store
                    from jaeger_ai.main import evict_session

                    cmd = str(req.get("cmd") or "")
                    command_args = req.get("args") or {}
                    sid = canonical_session_id(command_args.get("id"))
                    store = get_store(ctx.layout)
                    if store is None:
                        raise RuntimeError("no Jaeger session store is available")
                    if cmd == "create_session":
                        data = store.create(
                            sid,
                            origin=command_args.get("origin")
                            or command_args.get("source"),
                        )
                    elif cmd == "reconcile_session_transcript":
                        messages = command_args.get("messages")
                        user_messages = command_args.get("user_messages")
                        if isinstance(messages, list):
                            data = store.reconcile_visible_transcript(sid, messages)
                        elif isinstance(user_messages, list):
                            data = store.reconcile_visible_user_messages(sid, user_messages)
                        else:
                            raise ValueError("messages or user_messages must be a list")
                    elif cmd == "clear_session":
                        cleared = store.clear(sid)
                        evict_session(sid)
                        data = {"id": sid, "cleared": cleared}
                    else:
                        removed = store.delete(sid)
                        evict_session(sid)
                        data = {"id": sid, "removed": removed, "tombstoned": True}
                    _emit(proto, protocol.result_frame(
                        req.get("id"), data={"ok": True, **data}, ok=True))
                except Exception as exc:  # noqa: BLE001 — report through the contract
                    _emit(proto, protocol.result_frame(
                        req.get("id"), ok=False, error=str(exc)))
                continue
            if op == "command" and (req.get("cmd") or "") in {
                "configure_mcp_server", "enable_mcp_server", "disable_mcp_server",
                "remove_mcp_server", "reload_tools",
            }:
                a = req.get("args") or {}
                cmd = str(req.get("cmd") or "")
                try:
                    from jaeger_ai.core.mcp import service as mcp_service

                    if ctx.layout is None:
                        raise mcp_service.MCPServiceError("no Jaeger instance is selected")
                    if cmd == "configure_mcp_server":
                        data = mcp_service.configure_server(
                            ctx.layout, a.get("name"), a.get("config") or {})
                    elif cmd in {"enable_mcp_server", "disable_mcp_server"}:
                        data = mcp_service.set_server_enabled(
                            ctx.layout, a.get("name"), cmd == "enable_mcp_server")
                    elif cmd == "remove_mcp_server":
                        data = mcp_service.remove_server(ctx.layout, a.get("name"))
                    else:
                        data = mcp_service.reload_tools(ctx.layout)
                    _emit(proto, protocol.result_frame(req.get("id"), data=data, ok=True))
                except Exception as exc:  # noqa: BLE001 — report through the contract
                    _emit(proto, protocol.result_frame(
                        req.get("id"), ok=False, error=str(exc)))
                continue
            if op == "command" and (req.get("cmd") or "") in {
                "set_credential", "delete_credential",
            }:
                a = req.get("args") or {}
                cmd = str(req.get("cmd") or "")
                try:
                    from jaeger_ai.core import credential_service

                    if ctx.layout is None:
                        raise RuntimeError("no Jaeger instance is selected")
                    if cmd == "set_credential":
                        data = credential_service.set_credential(
                            ctx.layout, a.get("name"), a.get("value"))
                    else:
                        data = credential_service.delete_credential(
                            ctx.layout, a.get("name"))
                    _emit(proto, protocol.result_frame(req.get("id"), data=data, ok=True))
                except Exception as exc:  # noqa: BLE001 — report through the contract
                    _emit(proto, protocol.result_frame(
                        req.get("id"), ok=False, error=str(exc)))
                continue
            if op == "command" and (req.get("cmd") or "") == "configure_model":
                try:
                    from jaeger_ai.core.models.configuration import configure_model

                    if ctx.layout is None:
                        raise RuntimeError("no Jaeger instance is selected")
                    a = req.get("args") or {}
                    data = configure_model(
                        ctx.layout,
                        provider=a.get("provider"),
                        model=a.get("model"),
                        base_url=a.get("base_url"),
                        context_length=a.get("context_length"),
                        dry_run=bool(a.get("dry_run", False)),
                    )
                    # Writing config.yaml is not enough: the live client is
                    # the brain that answers. Without a hot swap, ARES shows
                    # the new pick while this process keeps serving the old
                    # one — and a same-id local Ollama model gets blamed on
                    # Ollama Cloud. Skip the swap while a turn is in flight.
                    if (
                        data.get("changed")
                        and not a.get("dry_run")
                        and not ctx.busy
                    ):
                        try:
                            from jaeger_ai.main import apply_live_model
                            applied = bool(apply_live_model())
                            data["applied"] = applied
                            if applied:
                                data["restart_required"] = False
                                boot = ctx.boot
                                if boot is not None:
                                    from jaeger_ai.main import _pipeline
                                    boot.client = _pipeline.get("client")
                                    ctx.client = boot.client
                        except Exception:  # noqa: BLE001
                            data["applied"] = False
                    _emit(proto, protocol.result_frame(req.get("id"), data=data, ok=True))
                except Exception as exc:  # noqa: BLE001 — report through the contract
                    _emit(proto, protocol.result_frame(
                        req.get("id"), ok=False, error=str(exc)))
                continue
            if op == "command" and (req.get("cmd") or "") == "configure_fallback_chain":
                try:
                    from jaeger_ai.core.models.configuration import (
                        configure_fallback_chain,
                    )

                    if ctx.layout is None:
                        raise RuntimeError("no Jaeger instance is selected")
                    a = req.get("args") or {}
                    data = configure_fallback_chain(
                        ctx.layout,
                        a.get("fallback") or a.get("entries") or [],
                        dry_run=bool(a.get("dry_run", False)),
                    )
                    _emit(proto, protocol.result_frame(req.get("id"), data=data, ok=True))
                except Exception as exc:  # noqa: BLE001
                    _emit(proto, protocol.result_frame(
                        req.get("id"), ok=False, error=str(exc)))
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
                    from jaeger_ai.core.settings.catalog import set_value
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
            if op == "command" and (req.get("cmd") or "") == "run_update":
                # In-app updates (0.8): shells out to `jaeger update`
                # (update_verb.run_update_subprocess) — never
                # reimplements the upgrade logic. Handled here (not
                # _command) so the result can carry restart_required +
                # the captured output as ``data``, same reason as
                # settings_set/new_session above. Refuses while a turn
                # is in flight (ctx.busy) — an update mid-turn would race
                # the turn's file/model reads against the product swap.
                if ctx.busy:
                    _emit(proto, protocol.result_frame(
                        req.get("id"), ok=False,
                        error="a turn is in flight — try again once it finishes"))
                    continue
                a = req.get("args") or {}
                try:
                    from jaeger_ai.cli.verbs.update_verb import run_update_subprocess
                    res = run_update_subprocess(ref=(a.get("ref") or None))
                    _emit(proto, protocol.result_frame(
                        req.get("id"),
                        data={"restart_required": res["restart_required"],
                              "returncode": res["returncode"],
                              "output": res["output"]},
                        ok=res["ok"], error=res.get("error")))
                except Exception as exc:  # noqa: BLE001 — reported, never crashes
                    _emit(proto, protocol.result_frame(
                        req.get("id"), ok=False, error=str(exc)))
                continue
            if op == "command" and (req.get("cmd") or "") == "new_session":
                # Runway item 4: the native "New Chat" button. Handled
                # here (not ``_command``) for the same reason as
                # settings_set/create_instance above — it needs to
                # return the minted id as ``data``, which the generic
                # _command -> (ok, error) shape can't carry. Evicting
                # the OLD session (when given) is best-effort cleanup —
                # the client is about to stop sending turns on that key
                # regardless, so a failure here would only leak state,
                # never break the new session.
                import uuid

                from jaeger_ai.main import evict_session
                a = req.get("args") or {}
                old_id = str(a.get("old_id") or "").strip()
                if old_id:
                    try:
                        evict_session(old_id)
                    except Exception:  # noqa: BLE001 — cleanup only
                        pass
                from jaeger_ai.core.sessions import get_store

                new_id = uuid.uuid4().hex[:8]
                store = get_store(ctx.layout)
                if store is not None:
                    store.create(new_id, origin="app")
                _emit(proto, protocol.result_frame(
                    req.get("id"), data={"id": new_id}, ok=True))
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
                    cmd = req.get("cmd") or ""
                    ok, err = _command(cmd, req.get("args") or {}, target)
                    _emit(proto, protocol.result_frame(req.get("id"), ok=ok, error=err))
                    # Surfaces rebrand from agent_state (name, card, icon)
                    # instead of waiting for the next turn or a restart.
                    if ok and cmd in ("select_character", "make_default"):
                        try:
                            name, icon = _active_character(target)
                            _emit(proto, protocol.agent_state_frame(
                                "ready", model=_model_name(target),
                                character=name, icon=icon,
                                agent_name=_display_name(target)))
                        except Exception:  # noqa: BLE001
                            pass
                continue
            # ``{"op":"send","text":...}`` (protocol) or legacy ``{"text":...}``.
            if (req.get("text") or "").strip():
                # 0.8.1 item 9: a send arriving while a turn is already in
                # flight was ALREADY never lost server-side — ``turns`` is a
                # plain FIFO queue.Queue drained by one worker thread, so it
                # just runs as the next normal turn (own state/reply frames)
                # once the worker is free. The gap was VISIBILITY: a naive
                # client had no signal that it queued instead of running
                # immediately (the Swift composer, e.g., assumed "busy"
                # meant "nowhere to put this" and dropped the text itself —
                # see ChatViewModel.send's isSending guard). Emit a small
                # v1-additive ack so a client can render a pending state.
                session = req.get("session") or "desktop-app"
                if ctx.busy:
                    ctx.session_pending[session] = ctx.session_pending.get(session, 0) + 1
                    _emit(proto, protocol.queued_frame(
                        session, ctx.session_pending[session]))
                req["_out"] = proto
                turns.put(req)
    finally:
        # Deregister before anything else: the os._exit below skips normal
        # cleanup, so a late release would leave a stale pid file behind.
        _pids.close()
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
        if ctx.supervisor_stop is not None:
            try:
                ctx.supervisor_stop.set()
            except Exception:  # noqa: BLE001
                pass
        if ctx.webhook_httpd is not None:
            try:
                ctx.webhook_httpd.shutdown()
            except Exception:  # noqa: BLE001
                pass
        if ctx.bridge_sock is not None:
            try:
                ctx.bridge_sock.close()
            except Exception:  # noqa: BLE001
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
        if own_process and (
                "llama_cpp" in sys.modules or "_pywhispercpp" in sys.modules):
            try:
                proto.flush()
                sys.stderr.flush()
            except Exception:  # noqa: BLE001
                pass
            os._exit(rc)

    return rc


if __name__ == "__main__":
    raise SystemExit(main(own_process=True))
