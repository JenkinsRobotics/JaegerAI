# JROS 0.8 — M2b: whisper_stt, the second engine-module

> subagent-driven. Recipe = kokoro_tts (M1) applied to STT. Spec conversion order: "stt (whisper)".

**Verified facts (M2b recon):** STT is 3 layers: `nodes/audio_session/` (bus contract; publishes `/sense/transcript`, `/sense/user_speech_start`, GateDecision — no whisper), `core/audio/session.py` `AudioSession` (mic/AEC/filter coordination; holds an injected `STTAdapter` **Protocol** :18-27, resolved via `plugins/whisper_stt/registry.py` — the Synthesizer pattern already exists), `plugins/whisper_stt/` (the engine: pywhispercpp two_pass/continuous; owns its own mic `_MicStream`, VAD worker, wake matching). Data flow node→session→adapter is direct calls, not bus. `nodes/stt/__init__.py` is a 3-line back-compat shim (pre-1.0 rule: delete). Config scattered: VoiceConfig (slot-generic), `AudioSessionConfig` dataclass (session.py:30-52), hardcoded engine knobs (pipeline.py:223-259). **Known gap to close:** `runtime._build_audio_session_node` (:370) always passes a default `AudioSessionConfig()` — config is not routed. `agent/tools/listen.py` has a second independent whisper model (leave standalone — atomic tool, no mic daemon; flag only). availability gates `listen` via `_TOOL_TO_PLUGIN` (plugin era) — must migrate to `_TOOL_TO_MODULE`.

**Design (kokoro precedent applied):** module owns node + engine; the slot-generic library (`core/audio/session.py`, AEC, filters) STAYS in core — it's the stt-slot library any engine would use; the STTAdapter protocol is the seam. Slot name: `stt`. Manifest node id stays `audio_session` (continuity), bound by `slot = "stt"`.

---

### Task A — the module: `jaeger_os/nodes/whisper_stt/`

Create `nodes/whisper_stt/`:
- `node.py` — `AudioSessionNode` moved verbatim from `nodes/audio_session/node.py` (class name kept).
- `engine/` — `plugins/whisper_stt/` moved wholesale (`_base.py`, `two_pass/`, `continuous/` if present, `registry.py`; keep internal structure; fix relative imports). The registry stays the engine-mode swap point.
- `module.yaml` — module: whisper_stt · slot: stt · version 1.0.0 · consumes: [] (owns its mic) · produces: [/sense/transcript, /sense/user_speech_start] · tools: [listen] · factory: `jaeger_os.nodes.whisper_stt:make_audio_session_node` · config: whisper_stt · requires: libraries [pywhispercpp, webrtcvad, sounddevice, numpy] (lifted from the old plugin.yaml; check its exact list).
- `__init__.py` — `make_audio_session_node` moved from `nodes/audio_session/__init__.py`; re-exports AudioSessionNode.
- `tests/` — one module-contract smoke (module.yaml validates; factory builds on an InProcBus with a fake STTAdapter; transcript publish round-trip).

Delete (no shims): `nodes/audio_session/`, `nodes/stt/` (the back-compat shim), `plugins/whisper_stt/` (incl. plugin.yaml — its requires move into module.yaml). Check the plugin registry/list_plugins consumers like M1 did (test_manifest, docstrings) and update.

Update importers: `runtime.py` (:40,:43 imports; `_build_audio_session_node`, `ensure_audio_session_node` — internals repoint, public API unchanged), `core/audio/session.py:173-186` `_build_adapter` (registry import path → `jaeger_os.nodes.whisper_stt.engine.registry`), manifests: `jaeger.windowed.toml` audio_session entry → `slot = "stt"` (keep `enabled = false` + the mic comment), root `jaeger.toml` likewise; availability.py: move `listen` from `_TOOL_TO_PLUGIN` to `_TOOL_TO_MODULE` → whisper_stt (fail-closed via discovery + requires_libraries probe, kokoro pattern); tests referencing old paths; `agent/tools/plugins.py` docstring; wizard/readiness/preflight if they name plugin paths.

Guarded imports (M2a pattern): any module-level import of `nodes.whisper_stt` in `nodes/__init__.py`/`runtime.py` gets the try/except guard so deleting the module dir degrades (listen + voice unavailable) instead of ImportError.

### Task B — module-owned config + close the routing gap

- `nodes/whisper_stt/config.py` — `WhisperSTTConfig(BaseModel)` with `_setting("whisper_stt", ...)` metadata (import from `setting_meta`, never schemas): `stt_mode: str = "two_pass"`, `fast_model_name: str = "base.en"`, `accurate_model_name: str = "medium.en"`, `vad_aggressiveness: int` + the key timing knobs worth operator exposure (`silence_hangover_ms`, `min_speech_ms`, `max_speech_ms`, `pre_roll_ms` — defaults lifted VERBATIM from pipeline.py:223-259; leave the rest hardcoded, YAGNI). Advanced-flag the timing knobs.
- Nest `Config.whisper_stt` via guarded leaf import + stand-in fallback in schemas.py (the kokoro :748 pattern).
- **Close the routing gap:** `runtime._build_audio_session_node` builds `AudioSessionConfig` FROM real config instead of defaults: engine fields from `Config.whisper_stt`, slot-generic fields from `Config.voice` (`wake_word`→require_wake_word, `follow_up_seconds`→followup_window_s, `barge_in`, `audio_backend`, `self_speech_*`). Map explicitly field-by-field; `AudioSessionConfig` stays the frozen dataclass boundary (session.py unchanged shape). Wire the engine knobs through `AudioSession._build_adapter`→registry `make(...)` if the plumbing already passes config; if a knob can't reach the engine without new plumbing, expose only what reaches (report which).
- Tests: catalog shows the `whisper_stt` group; `_build_audio_session_node` with a customized Config produces an AudioSessionConfig carrying those values; defaults byte-identical to today when config is untouched (regression pin).

### Gates
Per-dir suites green; **bench ≥79/81** (listen availability + tool surface touched); windowed headless boot (audio_session stays enabled=false — boot must not regress); catalog smoke; ledger. NO push.
