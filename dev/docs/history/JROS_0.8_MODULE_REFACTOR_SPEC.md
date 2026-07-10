# JROS 0.8 — runtime unification + node modules (approved spec)

**Status:** operator-approved 2026-07-07; execution begins now (branch `0.8.0`).
**Design lineage:** framework_vision.md + the 0.8 whitepaper §16 (0.8.0) + the
JP01 3.0 lessons. Operator framing: Mind-Body-Soul; ROS-style packages.

## Phase U — runtime unification (the socket modules plug into)
Two duplicated stacks exist (map: the 0.8.0 duality survey). Resolution:
- **Transport canon = `transport/`** (msgspec topics, Bus with `request()`):
  DELETE `app/bus/` (api/inproc/zmq); repoint `app/supervisor.py`, `app/core.py`,
  `core/messages.py`, `surfaces.make_bus_bridge` onto `transport.Bus`/`InProcBus`.
- **Supervision canon = `app/`** (Supervisor + manifest): replace
  `nodes/runtime.py` lazy singletons with Supervisor-managed nodes from
  `jaeger.toml` `[[node]]` factories (already written; flip `enabled=true`).
  Retire jp01 boot's hand-rolled `_start_nodes`/heartbeat.
- **One Node/NodeState** (`nodes/base.py`, keeps SIGUSR1; `FrameNode` moves
  beside it; `app/node.py` deleted or re-exports). **One NodeHealth** (msgspec
  `topics.NodeHealth`; `app/health.py` HealthCache consumes it; dataclass twin deleted).
- Gates: routing bench ≥79/81 (tts path touches the loop), full pytest suite,
  scenario suite security lane, and a windowed-app flow-walk before merge.

## Phase M — module format v1 + conversion
**The module IS the engine** (`kokoro_tts/`, not generic tts+adapters). The SLOT
defines the contract; swap engines by flipping the whole module.

```
jaeger_os/nodes/kokoro_tts/
  module.yaml     # slot: tts · consumes /act/speech · produces /sense/spoken,
                  #   /sense/tts_chunk · tools: [speak] · version · requires
  config.py       # the module's OWN settings schema (federated into the
                  #   unified settings catalog; namespaced)
  node.py         # engine-specific code (subclasses the ONE Node)
  tests/          # proves the slot contract in isolation
  README.md
```
- **Slot registry:** slot contract = topics in/out + lifecycle + settings shape
  + the TOOL SURFACE it serves (e.g. tts → `speak`). Tools stay stable across
  engine swaps ("the tool does the networking, the node does the execution" —
  the speak tool publishes /act/speech + awaits the ack; who *declares* it moves
  from hardcoded `agent/tools/` into slot registration). Instance config binds:
  `tts: kokoro_tts`. Missing module → graceful tool degradation.
- **Conversion order (current node set):** `kokoro_tts` (proof case, sets the
  format) → `stt` (whisper) → `audio_session` → `vision` → `motor` → `light` →
  `animation`/`media`. Each conversion: move code into the module dir, extract
  its settings schema from the central Config into module-owned (federated
  provider — extends the 0.7 schema-derived catalog), module.yaml, tests green.
- Hardware packages (JP01) become the same mechanism at larger scale — ratify
  after the operator's live JP01 walk.

## Process
Subagent-driven (plan per phase; per-task review; ledger `.superpowers/sdd/` in
JROS). Bench + suites are hard gates per task that touches the agent path.
