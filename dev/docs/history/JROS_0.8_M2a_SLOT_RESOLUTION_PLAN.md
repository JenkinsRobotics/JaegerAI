# JROS 0.8 — M2a: slot-resolution + graceful module removal

> subagent-driven. Makes the tts module's swap + remove properties REAL before converting other nodes.

**Verified facts (M2a map):** availability gate is ALREADY fail-closed (`_TOOL_TO_MODULE` → `discover_modules`; delete dir → agent never sees `text_to_speech`). Manifest binds nodes by factory string through `app._make_handle → resolve_ref(node.factory)`. `discover_modules()[slot]` yields the module's `factory`. Three MODULE-LEVEL imports crash the app if the dir is deleted: `nodes/__init__.py:27`, `nodes/runtime.py:45`, `agent/tools/speak.py:31` (+ light leaf `schemas.py:747` KokoroTTSConfig). `_speak_via_bus` (speak.py:173) already returns a clean dict on bus timeout — but hangs 180s first.

**Deliberate deferral (ponytail):** the SYNTH engine stays hardcoded in `runtime._default_synth_factory` (KokoroTTS). module.yaml declares only the *node* factory; slot-resolution binds that. A second real TTS engine is what forces synth-decoupling — YAGNI until then. M2a note it, don't build it.

---

### Task A — slot-resolution (manifest binds by slot, not factory string)

`jaeger_os/app/manifest.py`: add `slot: str = ""` to `NodeSpec` + the `_check_keys` allowlist; relax the thread-backend rule from "needs factory" to "needs factory OR slot".
`jaeger_os/app/app.py` `_make_handle`: BEFORE `resolve_ref`, if `node.slot and not node.factory`: look up `discover_modules()` (from `core/modules.py`), take the module for that slot, set `node.factory = spec.factory`. If the slot has zero modules → loud `_refuse`/raise naming the slot (fail-closed, don't silently skip a declared node). If >1 module for the slot → pick deterministically (first by module name sorted) and log which; multi-engine selection is a later config concern.
`jaeger.windowed.toml`: change the tts `[[node]]` from `factory = "jaeger_os.nodes.kokoro_tts:make_tts_node"` to `slot = "tts"` (drop the factory line) — proves the path end-to-end. Leave animation/audio_session as factory strings (not yet modules).
Tests: NodeSpec accepts slot; a manifest with `slot="tts"` resolves to kokoro_tts's factory and the node boots under the supervisor (extend the existing windowed-boot test); unknown slot raises naming the slot; factory-string path still works unchanged.

### Task B — graceful removal (no ImportError when the dir is gone)

Make the 3 module-level imports tolerate a missing module (try/except ImportError → None; annotations already lazy via `from __future__ import annotations` in runtime/speak):
- `nodes/__init__.py:27` — guard the `from .kokoro_tts import Synthesizer, TTSNode` re-export.
- `nodes/runtime.py:45` — guard; the `_tts_node` globals/type hints already string-friendly; `_default_synth_factory` (lazy import at :72) stays as-is (already lazy).
- `agent/tools/speak.py:31` — guard the `KOKORO_*`/`KokoroTTS` constant re-exports (fall back to None/defaults; the constants are only used when synthesizing, which won't happen if the module's gone).
- `schemas.py:747` — if guarding is clean, make `Config.kokoro_tts` optional when the leaf import fails; else leave (it's the light leaf, low crash risk) and note it.
Early no-module return in `_speak_via_bus` (speak.py): before the 180s `bus.request`, check the tts slot is present (reuse `availability._module_ready("text_to_speech")` or `discover_modules().get("tts")`); if absent return `{"spoken": False, "reason": "no tts module installed"}` immediately.
Test: with `discover_modules` monkeypatched to return no tts slot, importing `jaeger_os.nodes` / `runtime` / `speak` does NOT raise, and `speak()` returns the clean no-module dict without hanging. (Do NOT actually delete the dir in the test — monkeypatch discovery + simulate the ImportError path.)

### Gates
Per-dir suites (app, nodes, agent, core, interfaces) green; **bench ≥79/81** (speak path touched); windowed headless boot still supervises tts via the new `slot="tts"`; ledger updated. NO push.
