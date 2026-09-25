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

Liveness heartbeat (0.8 U3): every node publishes ``topics.NodeHealth``
on ``/sys/node/health`` from inside :meth:`run`'s own loop, throttled
to at most ~1/s regardless of ``tick_interval_s`` — best-effort, never
raises, never blocks the tick cadence.  ``app.health.HealthCache``
subscribes there so the chassis supervisor's ``diagnose()``/``ls()``
get real liveness data instead of listening on a topic nobody publishes.

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
import os
import signal
import sys
import threading
import time
from typing import Any

from jaeger_os.transport import Bus, topics

_HEARTBEAT_PERIOD_S = 1.0


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
                self.bus.subscribe(topics.SENSE_STT_TRANSCRIPT, self._on_transcript)

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
        #: Ticks that took longer than ``tick_period_s``. A rising
        #: count is a node asking for a rate its work cannot sustain,
        #: which is a fact rather than an impression.
        self._tick_overruns = 0
        self._stop_event = threading.Event()
        self._error: BaseException | None = None
        self._t_started_ns: int | None = None
        # OBSERVED I/O, for the bus catalog. A module.yaml declares
        # intent; these record what the node actually did, and the two
        # disagreeing is itself worth knowing.
        self._subscribed: set[str] = set()
        self._published: set[str] = set()
        # Telemetry, measured for EVERY node rather than hand-built per
        # module. "Is it alive" and "is it keeping up" are different
        # questions and only the second needs numbers.
        self._msgs_out = 0
        self._tick_count = 0
        self._tick_errors = 0
        self._window_ticks = 0
        self._window_msgs = 0
        self._window_started = time.monotonic()
        self._tick_rate_hz = 0.0
        self._tx_rate_hz = 0.0
        # Tick errors already reported, so WARN reflects NEW failures
        # rather than latching forever on one bad tick at boot.
        self._reported_tick_errors = 0
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

    # ── bus, with observation ────────────────────────────────────

    def subscribe(self, topic: str, callback) -> None:
        """Subscribe and record it. Subclasses may call
        ``self.bus.subscribe`` directly, but going through here is what
        puts the topic in this node's catalog entry."""
        self._subscribed.add(topic)
        self.bus.subscribe(topic, callback)

    def unsubscribe(self, topic: str, callback) -> None:
        self._subscribed.discard(topic)
        try:
            self.bus.unsubscribe(topic, callback)
        except Exception:  # noqa: BLE001
            pass

    def publish(self, msg) -> None:
        """Publish and record the topic.

        One set-add on the hot path — negligible beside the msgspec
        encode a cross-process publish already pays, and it is what
        makes ``publishes`` real rather than declared."""
        self._published.add(getattr(msg, "topic", ""))
        self._msgs_out += 1
        self._window_msgs += 1
        self.bus.publish(msg)

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
        last_heartbeat = 0.0   # 0.0 forces an immediate first heartbeat
        try:
            self._state = NodeState.SETTING_UP
            self._log(f"setup")
            self.setup()
            self._state = NodeState.RUNNING
            self._log(f"running")
            # Answer catalog requests so a surface attached after boot
            # still sees this node. Subscribed here rather than in
            # setup() so it works for every node without subclass
            # cooperation.
            try:
                self.subscribe(topics.SYS_NODE_META, self._on_meta_request)
            except Exception:  # noqa: BLE001
                pass
            self.announce()
            next_tick = time.monotonic()
            while not self._stop_event.is_set():
                try:
                    self.tick()
                    self._tick_count += 1
                    self._window_ticks += 1
                except Exception as exc:  # noqa: BLE001
                    self._tick_errors += 1
                    # Tick-level errors are recorded but don't stop
                    # the node by default — many nodes have transient
                    # I/O failures (mic underrun, network blip).
                    # Subclasses that want fail-fast behaviour can
                    # set self._error and self._stop_event in their
                    # tick handler.
                    self._log(f"tick error: {type(exc).__name__}: {exc}")
                now = time.monotonic()
                if now - last_heartbeat >= _HEARTBEAT_PERIOD_S:
                    last_heartbeat = now
                    self._publish_heartbeat()
                next_tick = self._pace(next_tick)
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

    # ── liveness heartbeat ────────────────────────────────────────

    def _on_meta_request(self, msg) -> None:
        """Re-announce when something asks. The request rides the same
        topic with an empty node name — ignore our own announcements and
        everyone else's, or nodes would answer each other forever."""
        if getattr(msg, "node", "") or getattr(msg, "state", "") != "request":
            return
        self.announce()

    def announce(self) -> None:
        """Publish this node's catalog entry on ``/sys/node/meta``.

        Called automatically on reaching RUNNING. Call it again after
        subscribing late, or in response to a catalog request, so a
        surface that attached after boot can still see the node.

        Best-effort like the heartbeat: introspection must never be able
        to take down the thing it describes.
        """
        try:
            self.bus.publish(topics.NodeMeta(
                node=self.name,
                node_class=type(self).__name__,
                state=self._state.value,
                # Exclude the meta topic itself: every node subscribes
                # to it for re-announce requests, so reporting it tells
                # a reader nothing and buries the node's real inputs.
                subscribes=sorted(
                    s for s in self._subscribed if s != topics.SYS_NODE_META),
                publishes=sorted(t for t in self._published if t),
                pid=os.getpid(),
                started_at_ns=self._t_started_ns or 0,
                node_id=self.name,
            ))
        except Exception:  # noqa: BLE001
            pass

    #: Seconds between ticks, paced by the framework. ``None`` — the
    #: default — means the node paces itself, which is right for a node
    #: that blocks on a queue or a device callback.
    #:
    #: Set it and you get DEADLINE scheduling: the next tick is due at
    #: a fixed interval from the last DUE time, not from when the last
    #: one finished. The difference is not subtle. A node asking for
    #: 100 Hz that sleeps its own period after 4 ms of work runs at
    #: 58.6 Hz — measured — because its real period is
    #: ``period + work``. Deadline-scheduled, the same node runs at
    #: 99.8 Hz.
    #:
    #: An overrun does NOT accumulate debt: if a tick takes longer than
    #: the period the schedule resets from now, so a slow patch causes
    #: a slow tick rather than a burst of catch-up ticks hammering a
    #: device that is already struggling.
    tick_period_s: float | None = None

    def _pace(self, next_tick: float) -> float:
        """Sleep until the next tick is due. Returns the new deadline."""
        if self.tick_period_s is None:
            return next_tick
        next_tick += self.tick_period_s
        delay = next_tick - time.monotonic()
        if delay > 0:
            # Wait on the stop event, not sleep(): a node with a 5 s
            # period must still shut down promptly.
            self._stop_event.wait(timeout=delay)
            return next_tick
        self._tick_overruns += 1
        return time.monotonic()

    def link_ok(self) -> bool | None:
        """Is the DEVICE this node owns actually reachable?

        ``None`` — the default — means "not a device node", and is
        correct for anything that owns no hardware.

        A ``kind: driver`` module MUST override this, and the module
        gates enforce it. The reason is a failure mode that produces no
        symptom: a node whose serial link died keeps ticking happily and
        reports RUNNING forever, because the tick loop is fine. It is
        the LINK that is gone, and nothing else in the system can tell.

        "The node is running" and "the motor controller is answering"
        are different facts, and only the second one means the robot is
        alive. Implement it as whatever proves the device is there —
        a ping, a status query, a watchdog counter that must advance.
        """
        return None

    def health_level(self) -> str:
        """Severity for this heartbeat. Override for domain rules.

        Default: ERROR if the node recorded a fatal error OR its device
        link is down, WARN if ticks have raised since the last
        heartbeat, otherwise OK. STALE is never returned here — a node
        that has stopped heartbeating cannot report that it stopped;
        only a consumer watching the clock can (see ``HealthCache``).

        A dead link is ERROR, not WARN, on purpose: a driver that
        cannot reach its device is not degraded, it is not doing its
        job. Reporting that as a warning is how a dead robot looks
        healthy on a dashboard.
        """
        if self._error is not None:
            return topics.HEALTH_ERROR
        try:
            if self.link_ok() is False:
                return topics.HEALTH_ERROR
        except Exception:  # noqa: BLE001
            # A link check that RAISES is a link that is down, not a
            # reason to lose the heartbeat carrying that news.
            return topics.HEALTH_ERROR
        if self._tick_errors > self._reported_tick_errors:
            return topics.HEALTH_WARN
        return topics.HEALTH_OK

    @staticmethod
    def _peak_memory_mb() -> float:
        """Peak RSS, stdlib only.

        ``resource`` rather than psutil so the framework keeps its
        dependency floor. Note this is PEAK, not current — enough to
        catch a node that ballooned, not enough to watch it breathe.
        The unit differs by platform: bytes on macOS, kilobytes on
        Linux."""
        try:
            import resource
            raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        except Exception:  # noqa: BLE001
            return 0.0
        return raw / (1024 * 1024) if sys.platform == "darwin" else raw / 1024

    def _publish_heartbeat(self) -> None:
        """Publish a ``topics.NodeHealth`` tick — throttled to ~1/s by
        :meth:`run`'s monotonic check, so a fast ``tick_interval_s``
        never floods the bus. Best-effort: a bus hiccup or a bad
        subscriber must never break the tick cadence or propagate out of
        the run loop.

        Carries measured telemetry (tick rate, publish rate, cumulative
        counts, peak memory) for every node. Rates are computed over the
        window since the last heartbeat, so "measured 9.8 Hz against a
        10 Hz interval" is answerable without any per-module work.

        Generic default — no hardware-link knowledge, so
        ``link_connected``/``last_controller_rx_age_s`` stay at their
        "not applicable" defaults. A hardware node that owns a physical
        link may override this to report real link detail instead.
        """
        now = time.monotonic()
        window = now - self._window_started
        if window > 0:
            self._tick_rate_hz = self._window_ticks / window
            self._tx_rate_hz = self._window_msgs / window
        self._window_ticks = 0
        self._window_msgs = 0
        self._window_started = now
        level = self.health_level()
        self._reported_tick_errors = self._tick_errors
        started = self._t_started_ns or 0
        try:
            try:
                link = self.link_ok()
            except Exception:  # noqa: BLE001
                link = False
            self.bus.publish(topics.NodeHealth(
                node=self.name,
                state=self._state.value,
                level=level,
                # False means "a link that SHOULD be up is down" —
                # the actionable signal. A node with no device
                # (link_ok() -> None) reports True, because there is no
                # link to have lost. Hardcoding False here made every
                # node in the system look disconnected.
                link_connected=(link is not False),
                last_controller_rx_age_s=0.0,
                detail="" if link is not False else "device link down",
                uptime_s=(time.time_ns() - started) / 1e9 if started else 0.0,
                tick_rate_hz=round(self._tick_rate_hz, 2),
                tx_rate_hz=round(self._tx_rate_hz, 2),
                msgs_out=self._msgs_out,
                tick_errors=self._tick_errors,
                memory_mb=round(self._peak_memory_mb(), 1),
                node_id=self.name,
            ))
        except Exception:  # noqa: BLE001 — heartbeat never breaks the node
            pass

    # ── log routing ──────────────────────────────────────────────

    def _log(self, msg: str, *, level: str = "info") -> None:
        """Tag log lines with the node name so multi-node output is
        readable.  Routes to stderr so it doesn't fight the TUI's
        stdout.

        One line shape for the whole system — a node, the supervisor and
        the chassis all render identically, because they all go through
        ``jaeger_os.app.logging.log``.  Imported inside the call rather
        than at module scope because ``app`` imports ``nodes``; a local
        import breaks that cycle the same way ``jaeger_os/__init__``'s
        PEP 562 lazy exports do.

        No ``bus=``: a node mirroring every line to ``/sys/log`` means a
        subscriber that logs feeds itself.  Mirroring stays an explicit
        choice the chassis makes, not a default nodes get.
        """
        from jaeger_os.app.logging import log
        log(self.name, msg, level=level)


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
