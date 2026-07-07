"""runtime.py — brain-side singleton for the bus + co-located nodes.

The brain (``main.py``) has tools that publish + wait for acks via
the Bus.  Those tools need a Bus to talk to AND need the matching
node to be running to receive their messages.  This module is the
lazy-boot singleton that holds both.

Two operations
--------------
* :func:`get_bus` returns the brain's :class:`InProcBus`,
  creating it on first call.
* :func:`ensure_tts_node` starts (and warms, on first call) the
  TTS node so ``/act/speech`` has a subscriber.  Idempotent — safe
  to call from any tool's first invocation OR from ``warm_kokoro``
  during boot prewarm.
* :func:`ensure_audio_session_node` starts the one mic/AEC/STT owner
  for monolithic voice mode, so TUI and other consumers read
  ``/sense/transcript`` instead of opening their own mic.

Track A.7 (the ZMQ broker) will add a multi-process variant: the
runtime asks the operator's ``--mode`` choice and either returns
``InProcBus`` (monolithic, today) or ``ZMQBus`` connected to a
broker (multiprocess).  Tools won't see the difference because
both implement the same Bus interface.

Shutdown
--------
:func:`shutdown` stops the TTS node, closes the bus, and clears
the singletons.  Idempotent.  Called from the brain's exit paths
so the Kokoro player teardown runs deterministically (lesson from
the 0.3.0 PortAudio segfault class).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from jaeger_os.core.audio import AudioSession, AudioSessionConfig
from jaeger_os.nodes.animation import AnimationNode, AvatarAutoStateDriver
from jaeger_os.nodes.animation import bridge as animation_bridge
from jaeger_os.nodes.audio_session import AudioSessionNode
from jaeger_os.nodes.base import NodeState
from jaeger_os.nodes.tts import Synthesizer, TTSNode
from jaeger_os.transport import Bus, InProcBus


_lock = threading.Lock()
_bus: Optional[Bus] = None
_bus_owned: bool = True   # False once a chassis/other boot root injects its bus
_tts_node: Optional[TTSNode] = None
_tts_thread: Optional[threading.Thread] = None
_synth = None  # KokoroTTS instance owned by the node
_audio_session_node: Optional[AudioSessionNode] = None
_audio_session_thread: Optional[threading.Thread] = None
_audio_session: Optional[AudioSession] = None
_animation_node: Optional[AnimationNode] = None
_animation_thread: Optional[threading.Thread] = None
_animation_bridge: Optional[animation_bridge.FrameBridge] = None
_avatar_auto_driver: Optional[AvatarAutoStateDriver] = None


def _default_bus_factory() -> Bus:
    return InProcBus()


def _default_synth_factory() -> Synthesizer:
    # Late import — speak.py imports from this module, so a module-level
    # import would be circular.
    from jaeger_os.plugins.kokoro_tts import KOKORO_LANG, KokoroTTS
    from jaeger_os.agent.tools.speak import _resolve_voice

    return KokoroTTS(voice=_resolve_voice(), lang=KOKORO_LANG)


def _default_tts_node_factory(
    *,
    bus: Bus,
    synthesizer: Synthesizer,
) -> TTSNode:
    return TTSNode(
        bus=bus,
        synthesizer=synthesizer,
        name="tts",
        install_signal_handlers=False,
    )


def _default_thread_factory(node: TTSNode) -> threading.Thread:
    return threading.Thread(
        target=node.run,
        name="brain-tts-node",
        daemon=True,
    )


def _default_audio_session_factory(
    config: AudioSessionConfig,
) -> AudioSession:
    # Wire the brain's LLM client + lock through so the node-owned
    # LLM gate (operator-locked 2026-06-07) can classify phrases
    # inside the session.  When the brain hasn't loaded yet (rare —
    # only voice-only configurations during early boot), the gate
    # degrades to deterministic filters and accepts unknown phrases.
    from jaeger_os.main import _pipeline
    llm_client = _pipeline.get("client")
    llm_lock = _pipeline.get("llm_lock")
    return AudioSession.build(
        config,
        tts_synth=get_synth(),
        llm_client=llm_client,
        llm_lock=llm_lock,
    )


def _default_audio_session_node_factory(
    *,
    bus: Bus,
    session: AudioSession,
) -> AudioSessionNode:
    return AudioSessionNode(
        bus=bus,
        session=session,
        name="audio_session",
        install_signal_handlers=False,
    )


def _default_audio_thread_factory(node: AudioSessionNode) -> threading.Thread:
    return threading.Thread(
        target=node.run,
        name="brain-audio-session-node",
        daemon=True,
    )


_bus_factory: Callable[[], Bus] = _default_bus_factory
_synth_factory: Callable[[], Synthesizer] = _default_synth_factory
_tts_node_factory: Callable[..., TTSNode] = _default_tts_node_factory
_thread_factory: Callable[[TTSNode], threading.Thread] = _default_thread_factory
_audio_session_factory: Callable[[AudioSessionConfig], AudioSession] = (
    _default_audio_session_factory
)
_audio_session_node_factory: Callable[..., AudioSessionNode] = (
    _default_audio_session_node_factory
)
_audio_thread_factory: Callable[[AudioSessionNode], threading.Thread] = (
    _default_audio_thread_factory
)


def get_bus() -> Bus:
    """Return the brain's singleton Bus, creating it on first call.

    Today: always :class:`InProcBus` unless :func:`set_bus` already
    injected one (a chassis's ``JaegerApp`` or ``boot_for_tui``).  Track
    A.7 will introduce a ZMQ variant chosen by the operator's ``--mode``
    flag.
    """
    global _bus, _bus_owned
    with _lock:
        if _bus is None:
            _bus = _bus_factory()
            _bus_owned = True
        return _bus


def set_bus(bus: Bus) -> None:
    """Inject the ONE process bus another boot root already owns, so
    every ``ensure_*`` call below — and the tools that invoke them
    (``speak``, ``avatar``, the audio session) — shares it instead of
    :func:`get_bus` lazily minting a second, disconnected ``InProcBus``.
    That duality was the pre-0.8-U3 windowed-app bug: the chassis
    (``JaegerApp``) built its own bus for the agent bridge while this
    module minted a completely separate one for TTS/animation, so
    neither side ever saw the other's messages.

    Call this from every boot root, in order:

    * ``JaegerApp._build_bus`` — right after constructing ``self.bus``.
    * ``boot_for_tui`` — via ``set_bus(get_bus())``; when no chassis ran
      first this just adopts ``get_bus()``'s own lazily-minted bus as
      the injected one (a no-op), formalising it as the ONE process bus
      for every subsequent caller (bridge, daemon, voice) on this path.

    Idempotent: calling again with the SAME bus object is a no-op.
    Marks the bus as chassis-owned (NOT owned by this module) so
    :func:`shutdown` never closes a bus its chassis is responsible for
    closing on its own teardown path — only the boot root that actually
    minted the bus may close it.
    """
    global _bus, _bus_owned
    with _lock:
        if _bus is bus:
            return
        _bus = bus
        _bus_owned = False


def ensure_tts_node(*, warm: bool = False) -> TTSNode:
    """Make sure a TTS node is running on the bus.  Idempotent.

    ``warm=True`` calls ``synth.warm()`` before returning so the
    Kokoro pipeline is preloaded — call this from
    :func:`jaeger_os.agent.tools.speak.warm_kokoro` at boot so the
    first user-facing ``text_to_speech`` doesn't pay the 5-7 s
    weight-load tax.
    """
    global _tts_node, _tts_thread, _synth
    bus = get_bus()
    synth_to_warm: Any = None
    with _lock:
        if _tts_node is None:
            _synth = _synth_factory()
            _tts_node = _tts_node_factory(bus=bus, synthesizer=_synth)
            _tts_thread = _thread_factory(_tts_node)
            _tts_thread.start()
            _wait_for_node_running(_tts_node, timeout_s=2.0)
        if warm and _synth is not None:
            synth_to_warm = _synth
        node = _tts_node
    if warm and synth_to_warm is not None:
        try:
            synth_to_warm.warm()
        except Exception:  # noqa: BLE001
            # Warm failure is non-fatal — the first speak() will
            # warm lazily.  Log but proceed.
            import sys
            print(
                "[runtime] kokoro warm at ensure_tts_node failed; "
                "first speak() will pay the load tax",
                file=sys.stderr, flush=True,
            )
    return node


def ensure_audio_session_node(
    *,
    config: AudioSessionConfig,
) -> AudioSessionNode:
    """Make sure exactly one audio session node owns the mic.

    The session factory receives the already-running TTS synth so
    monolithic AEC can share its ``reference_buffer`` directly.  This is
    intentional 0.4.0 coupling pending multiprocess reference transport.
    """
    global _audio_session_node, _audio_session_thread, _audio_session
    ensure_tts_node()
    bus = get_bus()
    with _lock:
        if _audio_session_node is None:
            _audio_session = _audio_session_factory(config)
            _audio_session_node = _audio_session_node_factory(
                bus=bus,
                session=_audio_session,
            )
            _audio_session_thread = _audio_thread_factory(_audio_session_node)
            _audio_session_thread.start()
            _wait_for_node_running(_audio_session_node, timeout_s=5.0)
        return _audio_session_node


def _wait_for_node_running(node: TTSNode, *, timeout_s: float) -> None:
    """Wait until ``node.setup()`` has completed.

    ``Node.run()`` sets state to RUNNING only after setup returns, so
    observing RUNNING means the TTS subscriber is installed.  This
    replaces the old fixed sleep which could race slow test or dev
    machines.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if node.state == NodeState.RUNNING:
            return
        if node.state == NodeState.FAILED:
            raise RuntimeError(
                f"TTS node failed during setup: {node.health().get('error')}"
            )
        time.sleep(0.01)
    raise TimeoutError("TTS node did not reach RUNNING state")


def ensure_animation_node(
    *,
    bridge_host: str = "127.0.0.1",
    bridge_port: int = 8765,
    enable_bridge: bool = True,
) -> AnimationNode:
    """Make sure an AnimationNode is running on the bus.  Idempotent.

    Spawns the FrameBridge WebSocket server alongside so connected
    renderers (the Swift app at ``jaeger_os/interfaces/avatar/``, an OBS browser
    source, debug tools) receive frames.  Pass ``enable_bridge=False``
    to skip the WS server — useful in headless tests and for the
    ``--no-avatar`` boot flag.

    Adapter registration: registers all L1-L4 vendored adapters
    (image, bitmap, sprite, gif, math) so the brain's
    ``set_avatar_state`` tool can route to any of them.
    """
    global _animation_node, _animation_thread, _animation_bridge
    bus = get_bus()
    with _lock:
        if _animation_node is not None:
            return _animation_node

        # Start the bridge first so the node's frame_callback can
        # plug into it.  Bridge runs on a daemon thread; failures
        # are non-fatal (animation still works, just no renderer
        # receives frames).
        bridge_instance: animation_bridge.FrameBridge | None = None
        if enable_bridge:
            try:
                bridge_instance = animation_bridge.FrameBridge(
                    host=bridge_host, port=bridge_port,
                )
                bridge_instance.start()
            except Exception:  # noqa: BLE001
                bridge_instance = None

        # Build the registry once so XP grants land on the same
        # tree the CLI + Swift app read.
        skill_registry: Any | None = None
        try:
            from jaeger_os.skill_tree import (
                SkillTreeRegistry, seed_default_tree,
            )
            from jaeger_os.core.instance.instance import (
                InstanceLayout, default_instance_name,
                resolve_instance_dir,
            )
            layout = InstanceLayout(
                root=resolve_instance_dir(default_instance_name()),
            )
            skill_registry = SkillTreeRegistry.for_instance(layout)
            seed_default_tree(skill_registry)
        except Exception:  # noqa: BLE001
            skill_registry = None

        frame_callback = (
            bridge_instance.publish_frame if bridge_instance else None
        )

        node = AnimationNode(
            bus=bus,
            skill_registry=skill_registry,
            frame_callback=frame_callback,
        )

        # Register the L1-L4 adapter set so the brain can route
        # to any of them by name.
        try:
            from jaeger_os.nodes.animation.adapters import (
                BitmapAdapter, GifAdapter, ImageAdapter,
                MathAdapter, SpriteAdapter,
            )
            node.register_adapter("image", ImageAdapter())
            node.register_adapter("bitmap", BitmapAdapter())
            node.register_adapter("sprite", SpriteAdapter())
            node.register_adapter("gif", GifAdapter())
            node.register_adapter("math", MathAdapter())
        except Exception:  # noqa: BLE001
            pass

        thread = threading.Thread(
            target=node.run,
            name="brain-animation-node",
            daemon=True,
        )
        thread.start()
        _wait_for_node_running(node, timeout_s=2.0)

        # 0.5 auto-state driver — flips Lilith's face to
        # "speaking" when TTS starts + back to "neutral" when
        # done.  Without this the avatar wouldn't react to TTS
        # unless the brain explicitly fired set_avatar_state
        # each turn.
        global _avatar_auto_driver
        auto_driver = AvatarAutoStateDriver(bus=bus)
        auto_driver.start()
        _avatar_auto_driver = auto_driver

        _animation_node = node
        _animation_thread = thread
        _animation_bridge = bridge_instance

    return _animation_node


def shutdown_animation_node() -> None:
    """Stop only the AnimationNode + bridge + auto-state driver.
    Idempotent."""
    global _animation_node, _animation_thread, _animation_bridge
    global _avatar_auto_driver
    with _lock:
        node = _animation_node
        thread = _animation_thread
        bridge_instance = _animation_bridge
        driver = _avatar_auto_driver
        _animation_node = None
        _animation_thread = None
        _animation_bridge = None
        _avatar_auto_driver = None
    if driver is not None:
        driver.stop()
    if node is not None:
        node.stop()
        if thread is not None:
            thread.join(timeout=3.0)
    if bridge_instance is not None:
        bridge_instance.stop()


def get_synth():
    """Expose the KokoroTTS instance the TTS node wraps.

    Used by ``warm_kokoro()`` so it can return Kokoro's own warm-
    report dict (matches the pre-0.4 signature)."""
    return _synth


def get_audio_session() -> AudioSession | None:
    """Return the monolithic audio session, if started."""
    return _audio_session


def shutdown_audio_session_node() -> None:
    """Stop only the audio session node, leaving TTS/bus alive."""
    global _audio_session_node, _audio_session_thread, _audio_session
    with _lock:
        audio_node = _audio_session_node
        audio_thread = _audio_session_thread
        _audio_session_node = None
        _audio_session_thread = None
        _audio_session = None
    if audio_node is not None:
        audio_node.stop()
        if audio_thread is not None:
            audio_thread.join(timeout=3.0)


def shutdown() -> None:
    """Stop the TTS, audio session, animation node; close the bus ONLY
    if this module minted it — a bus injected via :func:`set_bus` is a
    chassis's responsibility to close on its own teardown path.
    Idempotent."""
    global _bus, _bus_owned, _tts_node, _tts_thread, _synth
    global _audio_session_node, _audio_session_thread, _audio_session
    global _animation_node, _animation_thread, _animation_bridge
    global _avatar_auto_driver
    with _lock:
        audio_node = _audio_session_node
        audio_thread = _audio_session_thread
        anim_node = _animation_node
        anim_thread = _animation_thread
        anim_bridge = _animation_bridge
        auto_driver = _avatar_auto_driver
        node = _tts_node
        thread = _tts_thread
        bus = _bus
        bus_owned = _bus_owned
        _audio_session_node = None
        _audio_session_thread = None
        _audio_session = None
        _animation_node = None
        _animation_thread = None
        _animation_bridge = None
        _avatar_auto_driver = None
        _tts_node = None
        _tts_thread = None
        _bus = None
        _bus_owned = True
        _synth = None
    if auto_driver is not None:
        auto_driver.stop()
    if audio_node is not None:
        audio_node.stop()
        if audio_thread is not None:
            audio_thread.join(timeout=3.0)
    if anim_node is not None:
        anim_node.stop()
        if anim_thread is not None:
            anim_thread.join(timeout=3.0)
    if anim_bridge is not None:
        anim_bridge.stop()
    if node is not None:
        node.stop()
        if thread is not None:
            thread.join(timeout=3.0)
    if bus is not None and bus_owned:
        bus.close()
