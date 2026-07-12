"""JROS client protocol — the single wire contract for surfaces.

Lives in ``jaeger_os.contract`` (0.9 contract package) — frame shapes are
wire truth, not interface implementation. ``protocol_v1_fixtures.json``
lives beside this file; ``jaeger_os.interfaces.bridge`` builds these frames
and ``jaeger_os.interfaces.client.JrosClient`` parses them.

"Transports, not endpoints": one protocol, many transports. The Swift app
speaks it over stdio (``jaeger bridge``); the MCP server, a web backend, or
any third-party client speaks the *same* frames over the *same* SDK
(:class:`jaeger_os.interfaces.client.JrosClient`). A future WebSocket transport bridges
the in-process chassis bus to these identical frames — so a new surface is a
transport, not a re-implementation.

Frames are JSON objects, one per line (NDJSON):

  client → agent:
    {"op": "send",    "text": <str>, "session": <str?>}     # run one turn
    {"op": "respond", "id": <str>,   "answer": <str>}       # answer a request
    {"op": "quit"}                                          # graceful stop

  agent → client:
    {"type": "ready",   "instance": <str>, "model": <str?>}
    {"type": "state",   "busy": <bool>,    "session": <str?>}
    {"type": "tool",    "name": <str>, "phase": <start|done|error>,
                        "elapsed_s": <float>, "session": <str?>}
    {"type": "reply",   "text": <str>, "error": <str?>, "session": <str?>}
    {"type": "request", "id": <str>, "kind": <approval|clarify|secret>,
                        "prompt": <str>, "options": [<str>...], "session": <str?>}
    {"type": "fatal",   "error": <str>}                     # boot failed

This module is the ONE place these shapes live: the bridge builds them, the
client parses them, and the bus↔wire codec (``event_to_frame``) maps chassis
messages onto them. ``PROTOCOL_VERSION`` bumps on any breaking change.

``query``/``command`` are generic envelopes — ``what``/``cmd`` name the verb,
``args`` carries its payload, and adding one is additive (no version bump,
one branch in ``bridge.py``'s ``_query``/``_command``/``main``). The native
History surface (runway item 4, 0.8) added three:

  query   ``list_sessions`` {limit?}     -> [{id, title, preview,
                                              created_at, last_active,
                                              messages}, ...]
  query   ``load_session``  {id}         -> [{role, text, ts}, ...]  (also
                                             replays into the live agent —
                                             see ``main.resume_session_from_store``)
  command ``new_session``   {old_id?}    -> {id: <new session id>}  (evicts
                                             old_id when given)

In-app updates (0.8) added two more:

  query   ``check_update``  {}          -> {current, latest, available,
                                             notes_url}  (version_check.
                                             cached_update_status — cached
                                             ~6h under <instance>/run/, so a
                                             tray poll is cheap; never
                                             raises, degrades to
                                             available:false offline)
  command ``run_update``    {ref?}      -> {restart_required, returncode,
                                             output}  (shells out to
                                             `jaeger update`, the SAME
                                             machinery the CLI verb runs;
                                             refuses with an error while a
                                             turn is in flight)
"""

from __future__ import annotations

import json
from typing import Any

PROTOCOL_VERSION = "1"

# What this transport can do — sent in ``ready`` so a client can feature-gate
# instead of probing. A client seeing an unknown capability ignores it; a
# client MISSING one it needs degrades that feature, not the connection.
CAPABILITIES: tuple[str, ...] = (
    "query", "command", "chat", "sessions", "permissions", "agent_state",
)

# ── agent → client frame builders (used by the bridge / any transport) ──


def ready_frame(instance: str, model: str | None,
                character: str | None = None, icon: str | None = None,
                agent: str = "ready", agent_name: str | None = None) -> dict[str, Any]:
    # ``character`` = the active character's display name; ``icon`` = an absolute
    # path to its profile image. Both let the native client show the agent's face
    # + name in the tray/header, matching the PySide6 UI.
    #
    # v1 additions: ``proto`` + ``capabilities`` (so shell/core version skew
    # fails loudly instead of degrading silently) and ``agent`` — the agent
    # lifecycle state at handshake time. The bridge now emits ``ready`` the
    # moment the TRANSPORT is usable (queries/commands work immediately);
    # ``agent`` says whether the model is loaded ("ready") or still coming up
    # ("booting"), with ``agent_state`` frames streaming the transition.
    return {"type": "ready", "proto": PROTOCOL_VERSION,
            "capabilities": list(CAPABILITIES),
            "instance": instance, "model": model,
            "character": character, "icon": icon, "agent": agent,
            "agent_name": agent_name}


def agent_state_frame(state: str, model: str | None = None,
                      character: str | None = None, icon: str | None = None,
                      error: str | None = None,
                      agent_name: str | None = None) -> dict[str, Any]:
    """The agent lifecycle, decoupled from transport readiness:
    ``booting`` → ``ready`` (model/character attached) or ``failed``
    (``error`` says why; ``kind`` distinguishes a held instance lock).

    ``agent_name`` (v1 additive) is the AGENT's own name (identity.yaml — the
    unique robot the operator named); ``character`` is the persona it plays.
    Surfaces lead with ``agent_name`` so ``ready`` doesn't flash the character
    name before the ``identity`` query resolves. ``icon`` is the effective
    avatar (instance profile picture if set, else the character card)."""
    return {"type": "agent_state", "state": state, "model": model,
            "character": character, "icon": icon, "error": error,
            "agent_name": agent_name}


def state_frame(busy: bool, session: str = "") -> dict[str, Any]:
    return {"type": "state", "busy": busy, "session": session}


def result_frame(req_id: Any, data: Any = None, ok: bool = True,
                 error: str | None = None) -> dict[str, Any]:
    # Reply to a native client's {"op":"query"|"command", "id":…}. ``data`` holds
    # the query payload; ``ok``/``error`` report command success.
    return {"type": "result", "id": req_id, "ok": ok, "data": data, "error": error}


def tool_frame(name: str, phase: str, elapsed_s: float = 0.0,
               session: str = "", *, detail: str = "") -> dict[str, Any]:
    """``detail`` (v1 ADDITIVE, omitted when empty — clients must decode
    frames without it): short human context for the activity chip. Today
    only ``skill`` calls set it ("view scheduling"), so surfaces can show
    WHICH skill loaded instead of a bare tool name."""
    frame: dict[str, Any] = {"type": "tool", "name": name, "phase": phase,
                             "elapsed_s": float(elapsed_s), "session": session}
    if detail:
        frame["detail"] = detail
    return frame


def reply_frame(text: str, error: str | None = None,
                session: str = "", *,
                elapsed_s: float | None = None,
                ctx_used: int | None = None,
                ctx_max: int | None = None) -> dict[str, Any]:
    """One finished turn. v1 ADDITIVE telemetry (optional — the keys are
    OMITTED when unknown, and clients must decode frames without them):

      ``elapsed_s``  wall-clock seconds the turn took ("replied in 3s")
      ``ctx_used``   estimated prompt tokens the session occupies now
      ``ctx_max``    the loaded model's context window ("ctx 18.3K/32.8K")
    """
    frame: dict[str, Any] = {"type": "reply", "text": text, "error": error,
                             "session": session}
    if elapsed_s is not None:
        frame["elapsed_s"] = round(float(elapsed_s), 2)
    if ctx_used is not None:
        frame["ctx_used"] = int(ctx_used)
    if ctx_max is not None:
        frame["ctx_max"] = int(ctx_max)
    return frame


def request_frame(id: str, kind: str, prompt: str,
                   options: tuple[str, ...] | list[str] = (),
                   session: str = "") -> dict[str, Any]:
    return {"type": "request", "id": id, "kind": kind, "prompt": prompt,
            "options": list(options), "session": session}


def fatal_frame(error: str, kind: str = "boot",
                *, suggested_name: str | None = None) -> dict[str, Any]:
    """Unrecoverable failure — the bridge exits after this. ``kind``:
    ``boot`` (agent failed to start), ``locked`` (another process holds
    this instance's lock — the client should offer attach-or-pick-another,
    not a generic error), or ``no_instance`` (v1 additive: the resolved
    instance doesn't exist on disk yet — first-run. The transport STAYS
    alive for queries/commands so a native client can run onboarding and
    ``create_instance`` over the same pipe).

    ``suggested_name`` (v1 ADDITIVE, omitted when absent — clients must
    decode frames without it): only sent alongside ``kind="no_instance"``,
    the operator-pinned instance name (e.g. ``./jaeger agent create
    lilith``'s ``JAEGER_INSTANCE_NAME`` pin) so onboarding can default the
    identity step's name field to it instead of silently orphaning it
    behind whatever character the operator picks."""
    frame: dict[str, Any] = {"type": "fatal", "error": error, "kind": kind}
    if suggested_name:
        frame["suggested_name"] = suggested_name
    return frame


def queued_frame(session: str, position: int) -> dict[str, Any]:
    """v1 ADDITIVE (0.8.1 item 9): a ``send`` landed while a turn was already
    in flight. The bridge NEVER drops it — one worker thread drains a FIFO
    queue, so a send that arrives mid-turn just runs as the next normal
    turn (its own ``state``/``reply`` frames follow once it's up). This
    frame is purely a VISIBILITY signal so a client can render "queued"
    instead of assuming nothing happened. ``position`` counts THIS
    session's outstanding queued sends including this one (1 = next up)."""
    return {"type": "queued", "session": session, "position": int(position)}


def bye_frame(reason: str = "quit") -> dict[str, Any]:
    """Clean-shutdown marker: emitted right before the bridge exits on a
    ``quit`` op (or EOF), so the client can tell an ORDERLY exit from a
    crash even though the process may exit through ``os._exit`` (the ggml
    Metal teardown makes exit codes unreliable — see F1 in STATUS.md)."""
    return {"type": "bye", "reason": reason}


# ── client → agent op builders (used by the client SDK) ──


def send_op(text: str, session: str = "") -> dict[str, Any]:
    return {"op": "send", "text": text, "session": session}


def respond_op(id: str, answer: str) -> dict[str, Any]:
    return {"op": "respond", "id": id, "answer": answer}


def quit_op() -> dict[str, Any]:
    return {"op": "quit"}


# ── parsing ──


def parse(line: str) -> dict[str, Any] | None:
    """Parse one NDJSON line into a frame dict, or None if malformed / not a
    protocol frame (no ``type``/``op`` discriminator)."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict) or not ("type" in obj or "op" in obj):
        return None
    return obj


def encode(frame: dict[str, Any]) -> str:
    """Serialize a frame to one NDJSON line (newline included)."""
    return json.dumps(frame, ensure_ascii=False) + "\n"


# ── chassis-bus message → wire frame (for bus-attached transports) ──


def event_to_frame(msg: Any) -> dict[str, Any] | None:
    """Map a chassis ``/sense/*`` message to a wire frame, or None if the
    message isn't part of the client protocol. Lets a WebSocket/socket
    transport mirror the in-process bus to remote clients identically."""
    topic = getattr(msg, "topic", "")
    session = getattr(msg, "session", "") or ""
    if topic == "/sense/chat":
        return reply_frame(getattr(msg, "text", ""), None, session)
    if topic == "/sense/agent_state":
        return state_frame(getattr(msg, "state", "") == "thinking", session)
    if topic == "/sense/tool":
        return tool_frame(getattr(msg, "name", ""), getattr(msg, "phase", "start"),
                          getattr(msg, "elapsed_s", 0.0), session,
                          detail=getattr(msg, "detail", "") or "")
    if topic == "/sense/request":
        return request_frame(getattr(msg, "id", ""), getattr(msg, "kind", "approval"),
                             getattr(msg, "prompt", ""),
                             getattr(msg, "options", ()), session)
    return None
