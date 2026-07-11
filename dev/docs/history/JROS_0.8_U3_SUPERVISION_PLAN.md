# JROS 0.8 — U3: one runtime (bus merge + supervisor-owned nodes)

> subagent-driven; approved by operator 2026-07-07. Spec: JROS_0.8_MODULE_REFACTOR_SPEC.md Phase U.

**Verified topology (the U3 map):** only the windowed app has a real JaegerApp; TUI's is a slot-holder; bridge/daemon/voice have none. `runtime.get_bus()` mints its OWN InProcBus, so the windowed app runs TWO buses today. The `make_*` node factories ignore their `bus` arg (defer to `ensure_*`). Sole true type-collision on merge: `/sense/transcript` (chat dataclass vs msgspec from audio_session — AgentBridge would treat every `is_final=False` partial as a chat turn). NodeHealth: two types on two topics; `nodes/base.py` emits no heartbeat; HealthCache listens on the topic nobody publishes.

**Gates:** full suite; bench ≥79/81; scenario security lane; windowed boot smoke (bus identity + no double-spawn).

---

### Task A — one bus per process + collision fixes (safe on ALL entry paths)

1. **Bus injection.** `nodes/runtime.py`: add `set_bus(bus)`; `get_bus()` returns the injected bus if set, else mints as today (fallback keeps bare callers working). Inject at the two boot roots: `JaegerApp._build_bus` (after constructing `self.bus`, call `runtime.set_bus(self.bus)`) and `boot_for_tui` (construct/obtain the process bus once and `set_bus` it — if no JaegerApp, `get_bus()`'s lazily-minted one becomes the injected one so ALL callers share it). Idempotent; `runtime.shutdown()` clears the injection only if runtime owns the bus (never close a chassis-owned bus).
2. **Transcript collision guard.** `agent/loop/bridge.py` `_on_transcript`: ignore partials — `if not getattr(msg, "is_final", True): return`. THEN delete the `Transcript` dataclass from `core/messages.py` and subscribe `transport.topics.Transcript` (one type on `/sense/transcript`); update any imports.
3. **NodeHealth unification.** Canon = msgspec `topics.NodeHealth` on `/sense/node_health` (`SENSE_NODE_HEALTH`). Point `app/health.py` `HealthCache` at it; delete the dataclass twin (`app/health.py` NodeHealth + its registration/imports incl. `app/logging.py` LogLine untouched). Add a heartbeat to `nodes/base.py` `run()` loop: publish `topics.NodeHealth(node=name, state=state.value, ...)` every ~1s (best-effort, never raises). Retire jp01's hand-rolled `_start_health_heartbeat` (its nodes now heartbeat via base) — keep its EStop wiring.
4. Tests: bus-injection identity (boot → `runtime.get_bus() is app.bus`); partial-transcript ignored / final accepted; HealthCache receives a base-node heartbeat. Suite green.

### Task B — supervisor-backed nodes (windowed path graduates)

5. **Supervisor-backed `ensure_*`.** In `runtime.py`: if a supervisor is registered (add `set_supervisor(sup)`, called from `JaegerApp.boot` after supervisor start), `ensure_*` delegates: `supervisor.start(id)` if not running, and the accessors (`get_synth`, `get_audio_session`) read the supervised node's live object (supervisor exposes `node(id)` via ThreadHandle). No supervisor (TUI/bridge/daemon) → today's thread-spawn fallback, byte-identical.
6. **Manifest flip.** `jaeger.windowed.toml`: declare the tts/audio_session/animation `[[node]]` entries (enabled=true, thread, on_failure) — hardware_jp01 stays opt-in/disabled. Root `jaeger.toml`: update the "blocked by bus duality" header comment (duality resolved; nodes remain disabled there until the TUI path graduates). Because `ensure_*` is idempotent and both supervisor factory + tool calls resolve the same node on the same bus, no double-spawn — assert that in a test (boot windowed manifest headlessly, `ensure_tts_node()` returns the supervisor's node object).
7. Tests: supervisor-backed ensure returns the supervised node; fallback path (no supervisor) unchanged; restart policy still works on a supervised worker node. Suite green.

### Gates (after B)
Full suite · bench ≥79/81 · scenario security lane · windowed smoke (one bus, no double-spawn, chat round-trip if headless-drivable). Record in ledger; U3 complete → M1 (kokoro_tts module).
