"""AnimationNode — owns the active animation adapter; subscribes to
the bus; ships rendered frames to the renderer (Swift app at
``apps/JROS-Avatar/`` is the 0.5 default).

Architecture mirrors :class:`jaeger_os.nodes.tts.node.TTSNode`:
a subscriber on the bus + a worker thread that drains a queue of
play commands.  Each accepted command:

  1. Closes the current adapter (if any).
  2. Opens the adapter named in the :class:`AnimationCommand`.
  3. Streams frames until the clip ends OR a stop event arrives.
  4. Awards XP to the adapter's skill via the registry.
  5. Publishes :class:`AnimationState` updates on the bus so the
     operator's status surfaces (TUI, future visualisation) reflect
     reality.

For 0.5.0 the renderer integration is wired separately — this node
emits frame events; a small WebSocket bridge (lands in a later
commit) forwards them to the Swift app.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any

from jaeger_os import topics
from jaeger_os.nodes.base import Node
from jaeger_os.transport import Bus

from .base import AnimationAdapter, FrameBuffer


class AnimationNode(Node):
    """SUB ``/act/animation`` + ``/act/animation_stop`` → render
    frames → PUB ``/sense/animation_state``.

    Adapters are dependency-injected — :meth:`register_adapter` adds
    or replaces an entry in the adapter table.  Production
    instantiation registers all vendored Mochi adapters at boot.

    ``frame_callback`` is the seam to the renderer.  Tests pass a
    lambda that captures frames; the production WebSocket bridge
    pushes them to the Swift app.
    """

    def __init__(
        self,
        *,
        bus: Bus,
        skill_registry: Any | None = None,
        frame_callback: Any | None = None,
        name: str = "animation",
        queue_maxsize: int = 8,
        install_signal_handlers: bool = False,
    ) -> None:
        super().__init__(
            bus=bus,
            name=name,
            install_signal_handlers=install_signal_handlers,
        )
        self._adapters: dict[str, AnimationAdapter] = {}
        self._active: AnimationAdapter | None = None
        self._active_name: str = ""
        self._active_asset: str = ""
        self._active_started_at: float = 0.0
        self._stop_event = threading.Event()
        self._pending: "queue.Queue[topics.AnimationCommand]" = queue.Queue(
            maxsize=queue_maxsize,
        )
        self._skill_registry = skill_registry
        self._frame_callback = frame_callback

    # ── adapter registration ──────────────────────────────────────

    def register_adapter(self, key: str, adapter: AnimationAdapter) -> None:
        """Register an adapter under a string key (e.g. "gif",
        "image", "sprite").  The :class:`AnimationCommand` names the
        adapter by this key."""
        self._adapters[key] = adapter

    def known_adapters(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    # ── lifecycle ─────────────────────────────────────────────────

    def setup(self) -> None:
        self.bus.subscribe(topics.ACT_ANIMATION, self._on_command)
        self.bus.subscribe(topics.ACT_ANIMATION_STOP, self._on_stop)
        self._log(
            f"subscribed to {topics.ACT_ANIMATION} + "
            f"{topics.ACT_ANIMATION_STOP}"
        )

    def tick(self) -> None:
        """Drain one queued command per tick.  Frame rendering for
        the active adapter happens inside :meth:`_play` — running
        synchronously on the node thread keeps frame timing
        predictable."""
        try:
            msg = self._pending.get(timeout=0.1)
        except queue.Empty:
            return
        self._play(msg)

    def teardown(self) -> None:
        try:
            self.bus.unsubscribe(topics.ACT_ANIMATION, self._on_command)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.bus.unsubscribe(topics.ACT_ANIMATION_STOP, self._on_stop)
        except Exception:  # noqa: BLE001
            pass
        if self._active is not None:
            try:
                self._active.close()
            except Exception as exc:  # noqa: BLE001
                self._log(
                    f"adapter close error: {type(exc).__name__}: {exc}"
                )
            self._active = None

    # ── bus handlers ──────────────────────────────────────────────

    def _on_command(self, msg: topics.TopicMessage) -> None:
        assert isinstance(msg, topics.AnimationCommand)
        try:
            self._pending.put_nowait(msg)
        except queue.Full:
            self._log(
                f"animation queue full; dropped {msg.adapter!r} "
                f"clip {msg.asset_path!r}"
            )

    def _on_stop(self, msg: topics.TopicMessage) -> None:
        assert isinstance(msg, topics.AnimationStop)
        self._stop_event.set()

    # ── playback ──────────────────────────────────────────────────

    def _play(self, cmd: topics.AnimationCommand) -> None:
        adapter = self._adapters.get(cmd.adapter)
        if adapter is None:
            self._log(
                f"unknown adapter {cmd.adapter!r}; skipping clip "
                f"{cmd.asset_path!r}"
            )
            return
        # Close the previous adapter cleanly.
        if self._active is not None and self._active is not adapter:
            try:
                self._active.close()
            except Exception:  # noqa: BLE001
                pass
        params = dict(cmd.params or {})
        width = int(params.pop("width", 480))
        height = int(params.pop("height", 320))
        try:
            adapter.open(cmd.asset_path, width=width, height=height,
                         params=params)
        except Exception as exc:  # noqa: BLE001
            self._log(
                f"adapter open failed for {cmd.asset_path!r}: "
                f"{type(exc).__name__}: {exc}"
            )
            return
        self._active = adapter
        self._active_name = cmd.adapter
        self._active_asset = cmd.asset_path
        self._active_started_at = time.perf_counter()
        self._stop_event.clear()
        self._publish_state("playing", progress=0.0, elapsed_ms=0)
        # Stream frames until the clip ends, a stop arrives, or the
        # duration_ms cap (operator-specified) elapses.
        duration_s = cmd.duration_ms / 1000.0 if cmd.duration_ms else None
        try:
            self._stream_frames(adapter, duration_s)
        except Exception as exc:  # noqa: BLE001
            self._log(
                f"adapter stream error: {type(exc).__name__}: {exc}"
            )
        # Award XP on success — the adapter's skill grows whenever
        # it's used productively.
        skill_id = getattr(adapter, "skill_id", "")
        if skill_id and self._skill_registry is not None:
            try:
                self._skill_registry.award_xp(
                    skill_id, 1,
                    reason="animation_played",
                    metadata={"asset": cmd.asset_path},
                )
            except Exception:  # noqa: BLE001
                pass
        # Tear down active state.
        try:
            adapter.close()
        except Exception:  # noqa: BLE001
            pass
        self._active = None
        self._publish_state(
            "idle", progress=1.0,
            elapsed_ms=int(
                (time.perf_counter() - self._active_started_at) * 1000
            ),
        )

    def _stream_frames(
        self, adapter: AnimationAdapter, duration_s: float | None,
    ) -> None:
        # Frame pacing — adapters tell us how long each frame stays
        # visible via ``FrameBuffer.duration_ms``.  Default 33 ms
        # (~30 fps) if an adapter doesn't specify.
        while True:
            if self._stop_event.is_set():
                return
            elapsed = time.perf_counter() - self._active_started_at
            if duration_s is not None and elapsed >= duration_s:
                return
            frame = adapter.next_frame(elapsed)
            if frame is None:
                return
            self._emit_frame(frame)
            wait_ms = frame.duration_ms if frame.duration_ms > 0 else 33
            if self._stop_event.wait(timeout=wait_ms / 1000.0):
                return
            if frame.is_final:
                return

    def _emit_frame(self, frame: FrameBuffer) -> None:
        """Hand the frame to the renderer.  The frame callback is the
        bridge to the Swift app; in tests it captures frames for
        assertion.  Out-of-process renderers turn this into a
        WebSocket binary message + small JSON header."""
        if self._frame_callback is None:
            return
        try:
            self._frame_callback(frame)
        except Exception:  # noqa: BLE001
            # A renderer hiccup must never break the animation loop.
            pass

    def _publish_state(self, state: str, *, progress: float,
                       elapsed_ms: int) -> None:
        try:
            self.bus.publish(topics.AnimationState(
                adapter=self._active_name,
                asset_path=self._active_asset,
                state=state,
                progress=progress,
                elapsed_ms=elapsed_ms,
                node_id=self.name,
            ))
        except Exception:  # noqa: BLE001
            pass
