"""AgentBridge — the host-owned bridge between the bus and the agent.

The windowed app (and, later, the voice path) publish ``ChatMessage`` on
the bus; this bridge runs the **real** turn — ``jaeger_os.main.run_for_voice``,
the same universal logic the terminal TUI uses — and publishes
``ChatReply``. No surface ever imports the agent; it only speaks
``jaeger_os.core.messages``. Swap PySide6 for Swift and nothing here moves.

It is deliberately **not** a chassis ``Node``: the agent is Tier-1 (if it
dies, the app is down) — it's owned by the host, not the node supervisor,
and not restartable in isolation. It keeps a small host-component contract
(``start`` / ``stop`` / ``join`` / ``health``) so the host has real
observability without pretending to be supervised.

Tier-1 rule: only the agent publishes ``ChatReply``; a bad turn never
kills the bridge.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable

from jaeger_os.core.messages import (
    AgentActivity,
    AgentState,
    ChatMessage,
    ChatReply,
    ToolEvent,
)
from jaeger_os.transport import topics

# (client, text, session_key=...) -> {"text": str, "error": str | None, ...}
TurnFn = Callable[..., dict]

_DEFAULT_MAX_QUEUE = 32


class _BusEventAdapter:
    """Bridges the agent loop's internal event hook to the chassis bus.

    The loop publishes mid-turn observability through
    ``main._pipeline['event_bus'].publish(event_name, **payload)`` (the
    same hook the old daemon used to fan out to attach clients). We
    install one of these so those events land on the chassis bus as
    typed messages the surfaces render — live tool activity today."""

    def __init__(self, bus: Any) -> None:
        self._bus = bus
        self.current_session = ""   # set by the bridge before each turn

    def publish(self, event: str, **payload: Any) -> None:
        if event == "tool.progress":
            self._bus.publish(ToolEvent(
                name=str(payload.get("name", "")),
                phase=str(payload.get("phase", "start")),
                elapsed_s=float(payload.get("elapsed_s") or 0.0),
                session=self.current_session,
                detail=str(payload.get("detail", "")),
            ))
        elif event == "agent.activity":
            # The live progress stream — thoughts + tool actions the windowed
            # chat renders as dimmed lines distinct from the final reply.
            self._bus.publish(AgentActivity(
                kind=str(payload.get("kind", "status")),
                text=str(payload.get("text", "")),
                session=self.current_session,
            ))


class AgentBridge:
    """Bus ↔ in-process agent turn. ``client`` is the booted agent
    (``boot_for_tui().client``), loaded on the host's main thread (Metal-
    safe). Turns run on this bridge's own worker thread; the pipeline's
    ``llm_lock`` inside the turn function serializes model access.
    ``run_turn`` is injectable so the bridge is testable without a model."""

    def __init__(self, *, bus: Any, client: Any = None,
                 run_turn: TurnFn | None = None,
                 session_key: str = "gui",
                 max_queue: int = _DEFAULT_MAX_QUEUE) -> None:
        self.bus = bus
        self.client = client
        self._run_turn = run_turn
        self.session_key = session_key
        self._inbox: "queue.Queue[tuple[str, str]]" = queue.Queue(maxsize=max_queue)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._accepting = threading.Event()
        self._accepting.set()
        self._turn_active = threading.Event()
        # observability
        self.turns = 0
        self._state = "idle"          # idle | thinking | error | stopped
        self._last_error: str | None = None
        self._event_adapter: _BusEventAdapter | None = None
        self._confirm_provider: Any = None

    # ── host-component lifecycle ──────────────────────────────────

    def start(self) -> None:
        # Route the agent loop's mid-turn events (tool activity) onto the
        # chassis bus so surfaces render live tool use. Set after boot, so
        # ``_pipeline`` is populated.
        from jaeger_os.main import _pipeline
        self._event_adapter = _BusEventAdapter(self.bus)
        _pipeline["event_bus"] = self._event_adapter
        # Expose the chassis bus so in-process plugin bridges (telegram) can
        # answer mid-turn approval prompts in-channel, not just the desktop.
        _pipeline["chassis_bus"] = self.bus

        # Route permission prompts over the bus so a window / the Swift app
        # can answer — the console provider can't prompt from the agent
        # worker thread. Leave AllowAll (trusted unattended) untouched.
        try:
            from jaeger_os.agent.loop.bus_confirm import BusConfirmationProvider
            from jaeger_os.core.safety.permissions import (
                AllowAllProvider, current_policy)
            policy = current_policy()
            if not isinstance(policy.confirmation, AllowAllProvider):
                self._confirm_provider = BusConfirmationProvider(self.bus)
                policy.confirmation = self._confirm_provider
        except Exception:  # noqa: BLE001 — confirmation routing is best-effort
            self._confirm_provider = None

        self.bus.subscribe(ChatMessage.topic, self._on_chat)
        self.bus.subscribe(topics.SENSE_TRANSCRIPT, self._on_transcript)
        self._thread = threading.Thread(
            target=self._loop, name="agent-bridge", daemon=True)
        self._thread.start()
        self._publish_state("idle")

    def stop(self) -> None:
        """Stop accepting new turns, then signal the loop to exit after
        the in-flight turn finishes. Idempotent. Pair with :meth:`join`
        before tearing down the model."""
        self._accepting.clear()
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def health(self) -> dict[str, Any]:
        return {
            "state": self._state,
            "turns": self.turns,
            "queue_depth": self._inbox.qsize(),
            "turn_active": self._turn_active.is_set(),
            "last_error": self._last_error,
        }

    # ── bus → inbox (runs on the bus delivery thread) ─────────────

    def _on_chat(self, msg: ChatMessage) -> None:
        session = getattr(msg, "session", "") or self.session_key
        self._enqueue(getattr(msg, "source", "gui"), msg.text, session)

    def _on_transcript(self, msg: topics.Transcript) -> None:
        # Voice publishes incremental partials (is_final=False) while the
        # utterance is still being spoken, then one final. Only the final
        # is a chat turn — treating every partial as one would fire a
        # turn per fragment of a single sentence.
        if not getattr(msg, "is_final", True):
            return
        self._enqueue("voice", msg.text, self.session_key)   # STT → same inbox

    def _enqueue(self, source: str, text: str, session: str) -> None:
        if not self._accepting.is_set():
            return
        text = (text or "").strip()
        if not text:
            return
        # If a turn is already running, STEER it instead of queuing for the
        # next turn — every follow-up message redirects the live turn (it
        # lands as a user message before the next model step). Falls through
        # to the inbox if no agent turn is actually active.
        if self._turn_active.is_set() and _steer_active_turn(text):
            return
        try:
            self._inbox.put_nowait((source, text, session))
        except queue.Full:
            # Backstop — the surface should disable input while thinking,
            # but voice / other producers can still race the model.
            self.bus.publish(ChatReply(
                text="(busy — finishing the previous turn…)", session=session))

    # ── the loop (one turn per inbox item, off the bus thread) ───

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    _source, text, session = self._inbox.get(timeout=0.1)
                except queue.Empty:
                    continue
                if not (text or "").strip():
                    continue
                # Tag this turn's tool events + permission prompts with its
                # conversation so the right window renders/answers them.
                if self._event_adapter is not None:
                    self._event_adapter.current_session = session
                if self._confirm_provider is not None:
                    self._confirm_provider.current_session = session
                self._turn_active.set()
                self.turns += 1
                self._publish_state("thinking", session)
                try:
                    reply = self._run_one(text, session)
                except Exception as exc:  # noqa: BLE001 — a bad turn never kills tier 1
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    self._publish_state("error", session)
                    reply = f"(turn failed: {self._last_error})"
                # tier-1: only the agent replies — tagged with the session.
                self.bus.publish(ChatReply(text=reply, session=session))
                self._publish_state("idle", session, detail=_ctx_detail(session))
                self._turn_active.clear()
        finally:
            self._state = "stopped"

    def _run_one(self, text: str, session: str) -> str:
        run_turn = self._run_turn or _default_turn_fn()
        out = run_turn(self.client, text, session_key=session)
        if out.get("error"):
            return f"(agent error: {out['error']})"
        return out.get("text") or ""

    def _publish_state(self, state: str, session: str = "", detail: str = "") -> None:
        self._state = state
        self.bus.publish(AgentState(state=state, session=session, detail=detail))


def _steer_active_turn(text: str) -> bool:
    """Route a follow-up message into the in-flight turn as steering. The
    active agent's ``steer()`` lands it as a user message before its next
    model step, and returns True only when a turn was actually active and
    took it — so the bridge falls back to the inbox otherwise. Best-effort:
    never raises (a missing pipeline just means "queue it normally")."""
    try:
        from jaeger_os.main import _pipeline
        agent = _pipeline.get("active_jaeger_agent")
        return bool(agent.steer(text)) if agent is not None else False
    except Exception:  # noqa: BLE001 — steering is best-effort; fall back to the queue
        return False


def _default_turn_fn() -> TurnFn:
    # Lazy import: the heavy pipeline only loads when a real turn runs, so
    # importing this module (and its tests) stays cheap.
    from jaeger_os.main import run_for_voice
    return run_for_voice


def _ctx_detail(session: str) -> str:
    """``ctx 42%`` for the surfaces' status bar, or "" when unavailable.
    Best-effort: never let a missing pipeline break the post-turn publish."""
    try:
        from jaeger_os.main import last_ctx_snapshot
        snap = last_ctx_snapshot(session)
    except Exception:  # noqa: BLE001
        return ""
    return f"ctx {snap['pct']}%" if snap else ""
