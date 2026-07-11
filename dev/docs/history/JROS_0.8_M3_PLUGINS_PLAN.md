# JROS 0.8 — M3: the plugins family (graduation, gating, honest homes)

> subagent-driven. NOT a blind re-run of the node recipe — the M3 recon showed most
> plugins aren't bus-node-shaped. Each gets its honest treatment.

**Verified facts (M3 recon):** discord/telegram/imessage = agent-side bridge threads
(started via `activate_plugin`/autostart/`start_bridge`, `plugins/__init__.py:109`;
shared guts in `_messaging.py`; NOT chassis nodes). `homeassistant` + `ai_gen` = pure
agent-tool bundles registered on import — **their tools are UNGATED (fail-open)**:
absent from `_TOOL_TO_PLUGIN`/`_TOOL_TO_MODULE`, so a missing HASS token/`FAL_KEY`
doesn't hide them. `mcp/` = the MCP *client* (agent infra; availability already
prefix-gated; not module-shaped). `avaudio_io/` = a core audio LIBRARY (no
plugin.yaml; imported by kokoro_tts player, whisper engine, chimes, core/voice,
preflight, listen) living in plugins/ by accident of history. `voice_loop.py` +
`messaging_gateway.py` = daemon entry points, not plugins. `registry.py` = the
third-party extension API (orthogonal; untouched). `list_plugins()` scans
`plugins/*/plugin.yaml`; graduation = replace plugin.yaml with module.yaml and
add fail-closed gates (M1/M2b checklist: `_TOOL_TO_MODULE`, plugins.py docstrings
:279-296, test_modules/test_tool_availability_wiring).

**Design decisions:**
- **Messaging = the first multi-module slot, metadata-only (media precedent).**
  Each of discord/telegram/imessage gets a `module.yaml` (slot `messaging`) IN
  PLACE under plugins/ — `discover_modules()` grows a second root (plugins/) via a
  parameter, NOT a copy of the walker. No `[[node]]` entries (bridges aren't
  chassis nodes; `slot=` node binding assumes one-of, messaging is all-of). The
  launch path (`activate_plugin`/autostart) is UNCHANGED. `send_message`'s gate
  moves to module discovery with ANY-OF semantics: available iff ≥1 messaging
  module's requires are met (mirror the existing `_plugin_ready` messaging
  aggregate, availability.py:193-198, now fail-closed).
- **homeassistant + ai_gen keep plugin.yaml + `_TOOL_TO_PLUGIN` entries** (they
  remain plugins — correct shape for tool bundles) but get GATES: list every tool
  in `_TOOL_TO_PLUGIN` so `_plugin_ready` actually consults their manifest
  requires/env. Fixes the fail-open hole with zero structural churn.
- **avaudio_io → `core/audio/avaudio_io/`** — it IS core audio; pure move +
  import repoints (mechanical; grep-clean).
- **DEFERRED (not in M3):** relocating voice_loop/messaging_gateway (entry-point
  churn across tray/TUI/main while the voice path is the operator's daily surface
  — do it with the TUI-graduation cleanup); mcp/ stays agent infra; registry.py
  untouched; renaming the plugins/ dir itself (cosmetic).

---

### Task A — close the fail-open gates + avaudio_io home (no structure changes)

1. availability.py: add homeassistant's 4 tools (`ha_list_entities`, `ha_get_state`,
   `ha_list_services`, `ha_call_service`) → `"homeassistant"` and ai_gen's 2
   (`generate_image_fal`, `generate_video_fal`) → `"ai_gen"` in `_TOOL_TO_PLUGIN`.
   Verify `_plugin_ready` consults their plugin.yaml requires (env/libraries) and
   fails CLOSED for a listed-but-missing plugin (read the current semantics —
   if unknown-plugin is still fail-open, listed plugins with unmet requires must
   report unavailable; add tests for both directions).
2. Move `jaeger_os/plugins/avaudio_io/` → `jaeger_os/core/audio/avaudio_io/`;
   repoint every importer (kokoro_tts persistent_player, whisper engine _base,
   core/audio/chimes, core/voice, core/runtime/preflight, agent/tools/listen,
   cli/devtools — grep for the full list); grep-clean `plugins.avaudio_io`.
3. Per-dir suites green; no tool-surface text changes expected beyond the gates.

### Task B — messaging metadata modules (the multi-module slot)

1. `core/modules.py`: `discover_modules(roots: tuple[Path, ...] = (NODES_DIR, PLUGINS_DIR))`
   — same walker over both roots; keep the lru_cache; unknown-yaml still loud.
2. `module.yaml` in each of plugins/{discord,telegram,imessage}/ — slot `messaging`,
   `tools: [send_message]` (shared), `requires:` lifted from each plugin.yaml
   (libraries + env; imessage: platform darwin — if ModuleSpec lacks a platform
   field, add `requires_platform: []` with the same strictness). DELETE those three
   plugin.yaml files (graduation; list_plugins drops them — update plugins.py
   docstrings + tests per the M1/M2b checklist).
3. Availability: `send_message` availability = ANY discovered messaging module
   whose requires (libraries + env + platform) are met — fail-closed when none.
   Extend `_module_ready`/maps minimally (an aggregate entry, not a rewrite);
   the mid-turn `_BRIDGES` runtime check inside the tool itself stays as-is.
4. Tests: discovery returns 3 modules under slot messaging (multi-module slot);
   send_message available with ≥1 ready / unavailable with none (monkeypatched
   discovery + env); the launch path (`start_bridge` specs) untouched — pin with
   an existing test if present.

### Gates
Per-dir suites; **bench ≥79/81** (availability/tool surface touched — same
isolation rigor as M2b if a marginal row flips); catalog unchanged; ledger. NO push.
