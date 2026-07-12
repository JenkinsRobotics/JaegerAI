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

from jaeger_os.contract.ports import ANIMATION_BRIDGE_DEFAULT_PORT
from jaeger_os.core.audio import AudioSession, AudioSessionConfig
from jaeger_os.nodes.base import NodeState
try:
    from jaeger_os.nodes.animation import AnimationNode, AvatarAutoStateDriver
    from jaeger_os.nodes.animation import bridge as animation_bridge
except ImportError:
    # 0.8 M2c: same tolerance as the kokoro_tts/whisper_stt guards below
    # — every use of AnimationNode/AvatarAutoStateDriver/animation_bridge
    # is either a type annotation (stringified by the ``from __future__
    # import annotations`` above, so never evaluated) or reached only
    # through ``_construct_animation_components``/``_build_animation_node``,
    # which the availability gate (set_avatar_state/play_timeline/
    # warm_avatar -> animation module discovery) already keeps
    # unreachable when the module (or a library it requires, e.g.
    # websockets) is gone. None/inert here is the same failure mode as
    # before, just later.
    AnimationNode = None  # type: ignore[assignment,misc]
    AvatarAutoStateDriver = None  # type: ignore[assignment,misc]
    animation_bridge = None  # type: ignore[assignment]
try:
    from jaeger_os.nodes.kokoro_tts import Synthesizer, TTSNode
except ImportError:
    # 0.8 M2a: tolerate the kokoro_tts engine-module being removed —
    # every use below is either a type annotation (stringified by the
    # ``from __future__ import annotations`` above, so never evaluated)
    # or reached only through ``_default_synth_factory``'s OWN lazy
    # import (line ~72, unchanged), which is gated by the availability
    # check before the agent ever calls into TTS. So None here is
    # inert unless something actually tries to synthesize with no
    # module installed — the same failure mode as before, just later.
    Synthesizer = None  # type: ignore[assignment,misc]
    TTSNode = None  # type: ignore[assignment,misc]
try:
    from jaeger_os.nodes.whisper_stt import AudioSessionNode
except ImportError:
    # 0.8 M2b: same tolerance as the kokoro_tts guard above — every
    # use of AudioSessionNode below is either a type annotation
    # (stringified, never evaluated) or reached only through
    # ``_default_audio_session_node_factory``'s own construction call,
    # which the availability gate (``listen`` -> whisper_stt module
    # discovery) already keeps unreachable when the module is gone.
    AudioSessionNode = None  # type: ignore[assignment,misc]
from jaeger_os.transport import Bus, InProcBus


_lock = threading.Lock()
_bus: Optional[Bus] = None
_bus_owned: bool = True   # False once a chassis/other boot root injects its bus
_supervisor: Optional[Any] = None  # jaeger_os.app.supervisor.Supervisor, once registered
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
    from jaeger_os.nodes.kokoro_tts import KokoroTTS, KokoroTTSConfig
    from jaeger_os.agent.tools.speak import _resolve_voice
    from jaeger_os.core.context import _require_layout

    # 0.8 M1: lang comes from Config.kokoro_tts instead of a hardcoded
    # constant — the settings-catalog "kokoro_tts" group is only real
    # if changing it actually changes what gets built here. Voice
    # resolution (Identity.voice_id wins, module config is the
    # fallback default) lives in ``_resolve_voice`` itself.
    lang = KokoroTTSConfig().lang
    try:
        layout = _require_layout()
        from jaeger_os.core.instance.schemas import Config, load_yaml
        lang = load_yaml(layout.config_path, Config).kokoro_tts.lang
    except Exception:  # noqa: BLE001 — fresh/unconfigured instance
        pass
    return KokoroTTS(voice=_resolve_voice(), lang=lang)


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


def set_supervisor(sup: Any | None) -> None:
    """Register the chassis's ``Supervisor`` (0.8 U3b — "the windowed
    path graduates") so every ``ensure_*`` below delegates a
    manifest-declared, enabled node's lifecycle to it instead of
    spawning its own thread the way this module always has.

    Call from :meth:`JaegerApp.boot` right after ``supervisor.start_all()``
    returns — deliberately AFTER, not before: ``start_all()`` is what
    invokes ``make_tts_node``/``make_audio_session_node``/
    ``make_animation_node`` (the manifest's node factories) for the
    first time, and those factories construct their node DIRECTLY
    (see ``_build_tts_node`` et al.) rather than calling back into
    ``ensure_*_node`` — so there is no ordering hazard either way, but
    registering after keeps a clean "supervisor is fully up before
    anyone can be told to ask it for things" story. Call again with
    ``sup=None`` from :meth:`JaegerApp.shutdown` to clear the
    registration.

    No supervisor registered, or the manifest doesn't declare/enable
    the node in question → ``ensure_*`` falls back to today's
    byte-identical thread-spawn path. The TUI/bridge/daemon boot roots
    never call this at all, so they're unaffected either way.

    Clearing (``sup=None``) also tears down the AnimationNode's
    WebSocket bridge + :class:`AvatarAutoStateDriver` sidecars if this
    process ever built them under supervisor ownership — those two
    aren't part of what ``Supervisor.stop_all()`` tears down (it only
    knows about the ``AnimationNode`` object via its ``ThreadHandle``),
    so a supervised windowed-app shutdown would otherwise leak the
    bridge's daemon thread / bus subscriptions.
    """
    global _supervisor, _animation_bridge, _avatar_auto_driver
    with _lock:
        prior = _supervisor
        _supervisor = sup
        bridge_instance = None
        auto_driver = None
        if sup is None and prior is not None:
            bridge_instance = _animation_bridge
            auto_driver = _avatar_auto_driver
            _animation_bridge = None
            _avatar_auto_driver = None
    if auto_driver is not None:
        auto_driver.stop()
    if bridge_instance is not None:
        bridge_instance.stop()


def _build_tts_node(bus: Bus, config: dict[str, Any]) -> TTSNode:
    """Construct a :class:`TTSNode` directly on ``bus`` — the shape
    ``make_tts_node`` (the manifest's chassis-contract factory) hands
    the supervisor's ``ThreadHandle``.

    Deliberately does NOT call :func:`ensure_tts_node`: the supervisor
    invokes this factory from inside ``ThreadHandle.start()``, which
    is itself what ``ensure_tts_node``'s supervisor-delegation branch
    would call — recursing back in here would recurse into
    ``supervisor.start("tts")`` a second time while the first call is
    still on the stack (and ``self._node`` isn't assigned yet, so
    ``alive()`` can't short-circuit it). Constructing directly sidesteps
    the cycle entirely. Registers the synth/node into this module's
    globals so :func:`get_synth` (read by ``ensure_audio_session_node``'s
    session factory) and a later :func:`ensure_tts_node` call both see
    the SAME objects the supervisor is running.
    """
    global _synth, _tts_node
    synth = _synth_factory()
    node = _tts_node_factory(bus=bus, synthesizer=synth)
    if bool(config.get("warm", False)):
        try:
            synth.warm()
        except Exception:  # noqa: BLE001
            import sys
            print(
                "[runtime] kokoro warm at supervisor build failed; "
                "first speak() will pay the load tax",
                file=sys.stderr, flush=True,
            )
    with _lock:
        _synth = synth
        _tts_node = node
    return node


def ensure_tts_node(*, warm: bool = False) -> TTSNode:
    """Make sure a TTS node is running on the bus.  Idempotent.

    ``warm=True`` calls ``synth.warm()`` before returning so the
    Kokoro pipeline is preloaded — call this from
    :func:`jaeger_os.agent.tools.speak.warm_kokoro` at boot so the
    first user-facing ``text_to_speech`` doesn't pay the 5-7 s
    weight-load tax.
    """
    global _tts_node, _tts_thread, _synth
    sup = _supervisor
    if sup is not None and sup.has("tts") and sup.enabled("tts"):
        if not sup.is_running("tts"):
            sup.start("tts")
        node = sup.node("tts")
        if node is not None:
            with _lock:
                _tts_node = node
            if warm and _synth is not None:
                try:
                    _synth.warm()
                except Exception:  # noqa: BLE001
                    import sys
                    print(
                        "[runtime] kokoro warm at ensure_tts_node failed; "
                        "first speak() will pay the load tax",
                        file=sys.stderr, flush=True,
                    )
            return node
        # Supervisor declared "tts" but couldn't produce a live node
        # (setup failed) — fall through to the legacy path so callers
        # still get SOME usable node rather than propagating None.
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


def _load_audio_session_config() -> AudioSessionConfig:
    """Build the real :class:`AudioSessionConfig` from the instance's
    settings instead of construction defaults — closes the 0.8 M2b
    Task B routing gap (``_build_audio_session_node`` previously always
    passed ``AudioSessionConfig()``).

    Engine fields (``stt_mode``, ``fast_model_name``,
    ``accurate_model_name``) come from ``Config.whisper_stt``;
    slot-generic session fields come from ``Config.voice`` — mirrors
    the ``_require_layout()`` + ``load_yaml`` pattern
    ``kokoro_tts/engine.py``'s ``_resolve_backend``/
    ``_default_synth_factory`` already use for the sibling TTS module.

    ``wake_phrases`` is deliberately left at the dataclass default
    (``()``) — ``AudioSession._build_adapter`` falls back to
    ``_default_wake_phrases()`` when empty, and ``VoiceConfig`` carries
    no phrase-list field to route here.

    Falls back to ``AudioSessionConfig()`` defaults on any load failure
    (fresh/unconfigured instance) — same fallback shape as kokoro's
    synth factory; boot must not hard-fail because settings haven't
    been written yet.
    """
    try:
        from jaeger_os.core.context import _require_layout
        from jaeger_os.core.instance.schemas import Config, load_yaml

        layout = _require_layout()
        cfg = load_yaml(layout.config_path, Config)
    except Exception:  # noqa: BLE001 — fresh/unconfigured instance
        return AudioSessionConfig()
    return AudioSessionConfig(
        stt_mode=cfg.whisper_stt.stt_mode,
        fast_model_name=cfg.whisper_stt.fast_model_name,
        accurate_model_name=cfg.whisper_stt.accurate_model_name,
        require_wake_word=cfg.voice.wake_word,
        followup_window_s=cfg.voice.follow_up_seconds,
        barge_in=cfg.voice.barge_in,
        audio_backend=cfg.voice.audio_backend,
        self_speech_filter=cfg.voice.self_speech_filter,
        self_speech_threshold=cfg.voice.self_speech_threshold,
    )


def _build_audio_session_node(
    bus: Bus, config: dict[str, Any],
) -> AudioSessionNode:
    """Construct an :class:`AudioSessionNode` directly on ``bus`` — the
    shape ``make_audio_session_node`` hands the supervisor's
    ``ThreadHandle``. See :func:`_build_tts_node` for why this doesn't
    call :func:`ensure_audio_session_node` (recursion into
    ``supervisor.start("audio_session")`` mid-``start()``).

    0.8 M2b Task B: ``AudioSessionConfig`` is now built from real
    settings via :func:`_load_audio_session_config` instead of
    construction defaults — the manifest ``config`` dict param stays
    unused here (mirrors ``_build_tts_node``'s ``warm`` flag being the
    only manifest-config field it reads; audio_session's manifest node
    config carries no comparable per-boot flag today).
    """
    global _audio_session, _audio_session_node
    ensure_tts_node()  # dependency: shares the TTS synth's reference_buffer
    session = _audio_session_factory(_load_audio_session_config())
    node = _audio_session_node_factory(bus=bus, session=session)
    with _lock:
        _audio_session = session
        _audio_session_node = node
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
    sup = _supervisor
    if sup is not None and sup.has("audio_session") and sup.enabled("audio_session"):
        if not sup.is_running("audio_session"):
            sup.start("audio_session")
        node = sup.node("audio_session")
        if node is not None:
            with _lock:
                _audio_session_node = node
            return node
        # fall through to the legacy path if the supervisor couldn't
        # produce a live node (setup failed).
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


def _construct_animation_components(
    bus: Bus,
    *,
    bridge_host: str,
    bridge_port: int,
    enable_bridge: bool,
) -> tuple[AnimationNode, "animation_bridge.FrameBridge | None"]:
    """Pure construction: bridge + skill registry + ``AnimationNode`` +
    registered adapters. No locking, no thread spawn, no global writes
    — shared by the legacy :func:`ensure_animation_node` singleton path
    and the supervisor-facing :func:`_build_animation_node` factory so
    both build the exact same node shape."""
    # Start the bridge first so the node's frame_callback can plug
    # into it.  Bridge runs on a daemon thread; failures are non-fatal
    # (animation still works, just no renderer receives frames).
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

    return node, bridge_instance


def _build_animation_node(
    bus: Bus,
    *,
    bridge_host: str = "127.0.0.1",
    bridge_port: int = ANIMATION_BRIDGE_DEFAULT_PORT,
    enable_bridge: bool = True,
) -> AnimationNode:
    """Construct an :class:`AnimationNode` directly on ``bus`` — the
    shape ``make_animation_node`` hands the supervisor's
    ``ThreadHandle`` (no thread spawn — ``ThreadHandle.start()`` owns
    that; calling :func:`ensure_animation_node` here would recurse
    into ``supervisor.start("animation")`` mid-``start()``, same
    hazard as :func:`_build_tts_node`).

    Tears down + rebuilds the bridge/:class:`AvatarAutoStateDriver`
    sidecars fresh on every call rather than trying to reuse them —
    matching ``ThreadHandle.restart()``'s own philosophy ("never reuse
    a torn-down node object"). Without this, a supervisor-driven
    restart (crash → fresh ``AnimationNode`` from this factory) would
    leak the PRIOR bridge's daemon thread + the prior auto-driver's
    bus subscriptions, since neither is owned by the ``AnimationNode``
    object the supervisor's ``ThreadHandle`` tracks.
    """
    global _animation_bridge, _avatar_auto_driver
    with _lock:
        old_bridge = _animation_bridge
        old_driver = _avatar_auto_driver
        _animation_bridge = None
        _avatar_auto_driver = None
    if old_driver is not None:
        old_driver.stop()
    if old_bridge is not None:
        old_bridge.stop()

    node, bridge_instance = _construct_animation_components(
        bus, bridge_host=bridge_host, bridge_port=bridge_port,
        enable_bridge=enable_bridge,
    )
    auto_driver = AvatarAutoStateDriver(bus=bus)
    auto_driver.start()
    with _lock:
        _animation_bridge = bridge_instance
        _avatar_auto_driver = auto_driver
    return node


def ensure_animation_node(
    *,
    bridge_host: str = "127.0.0.1",
    bridge_port: int = ANIMATION_BRIDGE_DEFAULT_PORT,
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

    0.8 U3b: if a supervisor is registered AND the manifest declares
    + enables an "animation" node, delegates to it (starting it if
    not already running) and returns the SAME live object the
    supervisor manages — so a supervisor-driven restart is reflected
    here too, not a stale cached node.
    """
    global _animation_node, _animation_thread, _animation_bridge
    global _avatar_auto_driver
    sup = _supervisor
    if sup is not None and sup.has("animation") and sup.enabled("animation"):
        if not sup.is_running("animation"):
            sup.start("animation")
        node = sup.node("animation")
        if node is not None:
            with _lock:
                _animation_node = node
            return node
        # fall through to the legacy path if the supervisor couldn't
        # produce a live node (setup failed).
    bus = get_bus()
    with _lock:
        if _animation_node is not None:
            return _animation_node

        node, bridge_instance = _construct_animation_components(
            bus, bridge_host=bridge_host, bridge_port=bridge_port,
            enable_bridge=enable_bridge,
        )

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
    Idempotent.

    Also clears any registered supervisor (0.8 U3b) — a full runtime
    reset (the TUI/test pattern) shouldn't leave a stale delegation
    target behind for the next ``ensure_*`` call in the same process.
    """
    global _bus, _bus_owned, _tts_node, _tts_thread, _synth
    global _audio_session_node, _audio_session_thread, _audio_session
    global _animation_node, _animation_thread, _animation_bridge
    global _avatar_auto_driver, _supervisor
    with _lock:
        _supervisor = None
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
