# JROS 0.8 — M1: kokoro_tts, the first engine-module (sets the module format)

> subagent-driven. Spec: JROS_0.8_MODULE_REFACTOR_SPEC.md Phase M. Post-Phase-U runtime (one bus, Supervisor-owned nodes).

**Model (operator):** the module IS the engine. `nodes/kokoro_tts/` contains everything Kokoro: node, engine, its own config schema, module.yaml, tests. The SLOT (tts) defines the contract (topics, lifecycle, the `speak` tool); swapping engines = flipping the module. No back-compat shims (pre-1.0 rule): old paths are deleted, importers updated.

**Verified facts (M1 recon):** `nodes/tts/TTSNode` is engine-generic (Protocol-injected `Synthesizer`); the real engine is `plugins/kokoro_tts/` (`KokoroTTS`, persistent_player); the coupling point is `runtime.py:69 _default_synth_factory`; load-bearing importers of `nodes/tts` = `runtime.py:45` + the two toml factory strings; `agent/tools/speak.py:31` imports the plugin's constants; the settings catalog renders any new group automatically if the module's config model is nested under `Config`; tool registration = import-time decorator (keep `text_to_speech` in core — sandbox check stays central).

---

### Task 1 — the module: `jaeger_os/nodes/kokoro_tts/`

Create:
- `node.py` — today's `nodes/tts/node.py` moved verbatim (TTSNode + Synthesizer protocol; it's already clean).
- `engine.py` — `KokoroTTS` + constants moved from `plugins/kokoro_tts/node.py`; `persistent_player.py` moves alongside. The module owns its engine.
- `config.py` — `KokoroTTSConfig(BaseModel)`: `voice: str = "af_heart"` (default when Identity.voice_id unset), `lang: str = "a"`, `sample_rate: int = 24000` — each with `_setting("kokoro_tts", ...)` metadata (import `_setting` from `core/instance/schemas.py`). Nest into the central schema: `Config.kokoro_tts: KokoroTTSConfig` (one line in schemas.py) — the catalog walk then renders the `kokoro_tts` group with zero catalog edits. Voice resolution order unchanged: `Identity.voice_id` wins; module config is the default. Wire `_default_synth_factory` (runtime.py) to build from this config instead of hardcoded constants.
- `module.yaml` —
  ```yaml
  module: kokoro_tts
  slot: tts
  version: 1.0.0
  consumes: [/act/speech, /act/speech_stop]
  produces: [/sense/spoken, /sense/tts_chunk]
  tools: [text_to_speech]
  factory: jaeger_os.nodes.kokoro_tts:make_tts_node
  config: kokoro_tts        # its group/key in the settings catalog
  ```
- `__init__.py` — `make_tts_node` (the post-U3 direct-build factory, moved), re-exports `TTSNode, Synthesizer, KokoroTTS`.
- `tests/` — move `dev/tests/jaeger_os/nodes/test_tts.py` + `test_tts_chunk_lipsync.py` content? NO — repo tests stay under `dev/tests` (suite discovery); instead `nodes/kokoro_tts/tests/` gets one module-contract smoke (module.yaml validates; factory builds a node on an InProcBus; speak round-trip with a fake synth) and dev/tests keep running against the new paths.

Delete (no shims): `jaeger_os/nodes/tts/` and `jaeger_os/plugins/kokoro_tts/` — BUT first check how `plugins/` are discovered (a plugin registry may list kokoro_tts; update its registry/docs accordingly; if plugin.yaml metadata is consumed at runtime, fold what matters into module.yaml and report what was dropped).

Update importers: `runtime.py:45` import + `_default_synth_factory` + `_build_tts_node`; `agent/tools/speak.py:31` (constants now from `jaeger_os.nodes.kokoro_tts`); `jaeger.windowed.toml` + root `jaeger.toml` factory strings → `jaeger_os.nodes.kokoro_tts:make_tts_node`; `plugins/voice_loop.py:255` `_get_tts` path if it imports the plugin; tests (`test_tts.py`, `test_tts_chunk_lipsync.py`, `test_runtime.py`, `dev/scripts/tts_node_test.py`); docstring mentions best-effort.

### Task 2 — module.yaml loader (the seam, minimal)

`jaeger_os/core/modules.py` (new, small): `ModuleSpec` (msgspec or pydantic, match repo norm: module/slot/version/consumes/produces/tools/factory/config), `load_module(dir) -> ModuleSpec` (reads+validates module.yaml; unknown keys refused), `discover_modules(root=jaeger_os/nodes) -> dict[slot, list[ModuleSpec]]`. NO manifest.py changes: manifests keep explicit factory strings for now (module.yaml is authoritative metadata; slot-resolution binding is a later step). Tests: valid kokoro_tts module.yaml loads; bad slot/missing factory refused; discovery finds kokoro_tts under the tts slot.

### Gates
Per-dir suites (nodes, agent, core, app, interfaces) green; settings catalog exposes the `kokoro_tts` group (`python -c` smoke printing catalog groups); windowed headless boot still supervises the tts node under the new factory; **bench ≥79/81** (speak path touched); ledger updated.
