"""base.py — Node base class.

Track A.5 of the 0.4 roadmap.

A Node is a long-lived unit of work with a four-phase lifecycle:

  setup     called once when the supervisor starts the node.  Open
            files, build models, subscribe to topics, register tools.
  tick      called repeatedly while the node is running.  Subclasses
            override to do real work.  The default implementation
            sleeps briefly so a Node that only listens (publishes
            via subscriber callbacks) doesn't busy-loop.
  teardown  called once when the supervisor stops the node.  Flush,
            close files, drop subscriptions.
  health    queryable any time.  Returns a dict the supervisor
            (Track D) treats as opaque + forwards to any operator-
            facing health surface.

Signals
-------
* SIGTERM  → graceful shutdown.  ``stop()`` flips the state to
             STOPPING, the run loop exits its tick, and teardown
             runs.
* SIGUSR1  → request-restart.  ``stop()`` flips to RESTARTING; the
             supervisor reads the state on teardown and decides
             whether to actually re-spawn.  At A.5 this is just the
             plumbing — the supervisor lives at Track D.
* SIGINT   → handled as SIGTERM (Ctrl-C during dev).

Threading
---------
The node runs in its own thread or its own process — the Node
class doesn't care which.  ``run()`` is the entry point either way.
Subclasses MUST be thread-safe in their tick handler; they MUST NOT
make blocking calls that exceed ``tick_timeout_s`` (default 5.0)
or the supervisor will assume the node has wedged.
"""

from __future__ import annotations

import abc
import enum
import signal
import sys
import threading
import time
from typing import Any

from jaeger_os.transport import Bus


class NodeState(str, enum.Enum):
    """Node lifecycle state.  ``str`` mix-in so it serialises clean."""
    INIT = "init"
    SETTING_UP = "setting_up"
    RUNNING = "running"
    STOPPING = "stopping"   # graceful shutdown requested (SIGTERM/stop())
    RESTARTING = "restarting"  # supervisor should re-spawn (SIGUSR1)
    STOPPED = "stopped"
    FAILED = "failed"       # setup/tick raised; teardown still runs


class Node(abc.ABC):
    """Long-lived unit of work with lifecycle + bus integration.

    Subclasses MUST override :meth:`name` (or pass it to ``super().__init__``)
    so log lines + topic envelopes can identify the source.  They
    SHOULD override :meth:`tick` to do work; the default sleeps.
    They MAY override :meth:`setup` / :meth:`teardown` / :meth:`health`
    as needed.

    Example (illustrative — not used in production)::

        class EchoNode(Node):
            def setup(self):
                self.bus.subscribe(topics.SENSE_TRANSCRIPT, self._on_transcript)

            def _on_transcript(self, msg):
                self.bus.publish(topics.SpeechCommand(
                    text=f"You said: {msg.text}",
                    correlation_id=msg.correlation_id,
                ))
    """

    def __init__(
        self,
        *,
        bus: Bus,
        name: str | None = None,
        tick_interval_s: float = 0.1,
        install_signal_handlers: bool = True,
    ) -> None:
        self.bus = bus
        self._name = name or self.__class__.__name__
        self._tick_interval_s = tick_interval_s
        self._state = NodeState.INIT
        self._stop_event = threading.Event()
        self._error: BaseException | None = None
        self._t_started_ns: int | None = None
        # Signal handlers are off by default in tests + when the
        # node runs on a non-main thread (signal raises ValueError
        # in either case).  ``./launch`` flips this on for the main
        # supervised node in a subprocess.
        if install_signal_handlers:
            try:
                signal.signal(signal.SIGTERM, self._on_signal)
                signal.signal(signal.SIGINT, self._on_signal)
                if hasattr(signal, "SIGUSR1"):
                    signal.signal(signal.SIGUSR1, self._on_restart_signal)
            except (ValueError, OSError):
                # Signal handlers can only be installed on the main
                # thread of the main interpreter.  Tests typically
                # run nodes on background threads; that's OK.
                pass

    # ── identity ─────────────────────────────────────────────────

    @property
    def name(self) -> str:
        """Stable identifier used in log routing and topic envelopes.
        Subclasses should set this via the ``name=`` kwarg or by
        overriding the property."""
        return self._name

    @property
    def state(self) -> NodeState:
        return self._state

    # ── lifecycle hooks (override these) ─────────────────────────

    def setup(self) -> None:
        """Run once when the node starts.  Override to open files,
        build models, register subscribers.  Raise to abort startup."""

    def tick(self) -> None:
        """Run repeatedly while the node is running.  Default is a
        short sleep so listen-only nodes (which work via subscriber
        callbacks) don't busy-loop.  Override to do periodic work
        (mic frame poll, encoder read, etc.)."""
        time.sleep(self._tick_interval_s)

    def teardown(self) -> None:
        """Run once when the node stops.  Override to flush logs,
        close handles, drop subscriptions.  Runs even if setup/tick
        raised."""

    def health(self) -> dict[str, Any]:
        """Snapshot of the node's liveness.  Default returns the
        envelope expected by Track D's supervisor.  Subclasses can
        extend with subsystem-specific fields (queue depths, dropped
        frame counters, model load state).
        """
        uptime_s = 0.0
        if self._t_started_ns is not None:
            uptime_s = (time.time_ns() - self._t_started_ns) / 1e9
        return {
            "name": self.name,
            "state": self._state.value,
            "uptime_s": uptime_s,
            "error": (
                None if self._error is None
                else f"{type(self._error).__name__}: {self._error}"
            ),
        }

    # ── run / stop ────────────────────────────────────────────────

    def run(self) -> None:
        """Run the node lifecycle to completion.  Blocks until stop()
        is called or a signal triggers shutdown."""
        self._t_started_ns = time.time_ns()
        try:
            self._state = NodeState.SETTING_UP
            self._log(f"setup")
            self.setup()
            self._state = NodeState.RUNNING
            self._log(f"running")
            while not self._stop_event.is_set():
                try:
                    self.tick()
                except Exception as exc:  # noqa: BLE001
                    # Tick-level errors are recorded but don't stop
                    # the node by default — many nodes have transient
                    # I/O failures (mic underrun, network blip).
                    # Subclasses that want fail-fast behaviour can
                    # set self._error and self._stop_event in their
                    # tick handler.
                    self._log(f"tick error: {type(exc).__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            # Setup-level errors are fatal — record + propagate to
            # teardown.
            self._error = exc
            self._state = NodeState.FAILED
            self._log(f"setup failed: {type(exc).__name__}: {exc}")
        finally:
            try:
                self.teardown()
            except Exception as exc:  # noqa: BLE001
                self._log(f"teardown error: {type(exc).__name__}: {exc}")
                if self._error is None:
                    self._error = exc
            if self._state != NodeState.FAILED:
                if self._state == NodeState.RESTARTING:
                    self._log("restart requested")
                else:
                    self._state = NodeState.STOPPED
                    self._log("stopped")

    def stop(self) -> None:
        """Request graceful shutdown.  The run loop will exit its
        current tick + run teardown.  Idempotent."""
        if self._state in (NodeState.STOPPING, NodeState.STOPPED,
                           NodeState.FAILED, NodeState.RESTARTING):
            return
        self._state = NodeState.STOPPING
        self._stop_event.set()

    def request_restart(self) -> None:
        """Request the supervisor restart this node after teardown.
        Distinct from :meth:`stop` so the supervisor (Track D) can
        decide whether to actually re-spawn.  Idempotent."""
        self._state = NodeState.RESTARTING
        self._stop_event.set()

    # ── signal handlers ──────────────────────────────────────────

    def _on_signal(self, signum: int, frame: Any) -> None:
        self._log(f"received signal {signum}; stopping")
        self.stop()

    def _on_restart_signal(self, signum: int, frame: Any) -> None:
        self._log(f"received signal {signum}; restart requested")
        self.request_restart()

    # ── log routing ──────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        """Tag log lines with the node name so multi-node output is
        readable.  Routes to stderr so it doesn't fight the TUI's
        stdout."""
        print(f"[node:{self.name}] {msg}", file=sys.stderr, flush=True)


class FrameNode(Node):
    """Render-loop specialization — the MochiNodeBase shape, formatted.

    Fixed-rate scheduling (deadline-based, so render cost doesn't
    drift the frame rate) with the update/render split Mochi's nodes
    already use:

        update_tick(ts)   advance state — scripts, state machines
        render_tick(ts)   produce + publish one frame

    A node that falls behind resyncs to "now" rather than spiraling.
    """

    def __init__(self, *, bus: Any, fps: float = 30.0,
                 **kwargs: Any) -> None:
        super().__init__(bus=bus,
                         tick_interval_s=1.0 / max(float(fps), 0.5),
                         **kwargs)
        self.fps = float(fps)
        self.frames_rendered = 0
        self._next_deadline: float | None = None

    # override these two, not tick():

    def update_tick(self, ts: float) -> None:
        """Advance state. Default: nothing."""

    def render_tick(self, ts: float) -> None:
        """Produce + publish one frame. Default: nothing."""

    def tick(self) -> None:
        now = time.monotonic()
        if self._next_deadline is None:
            self._next_deadline = now
        self.update_tick(now)
        self.render_tick(now)
        self.frames_rendered += 1
        self._next_deadline += self._tick_interval_s
        sleep_s = self._next_deadline - time.monotonic()
        if sleep_s > 0:
            time.sleep(sleep_s)
        else:
            self._next_deadline = time.monotonic()   # fell behind; resync

    def health(self) -> dict[str, Any]:
        base = super().health()
        base["fps_target"] = self.fps
        base["frames_rendered"] = self.frames_rendered
        return base
