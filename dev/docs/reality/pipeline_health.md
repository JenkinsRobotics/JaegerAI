# Pipeline Health — focus areas for future improvement

Consolidated from the reference docs in `dev/docs/pipelines/` (each verified
against code). This is the "what's solid / what's incomplete / what's not wired /
what's misleading" snapshot, so future work has a target list. Dated 2026-07-01.

## At a glance

| Pipeline | State | Headline |
|----------|-------|----------|
| Agent turn loop | 🟢 good (migration flag murky) | `JaegerAgent.run_turn` loop is live |
| Skill discovery | 🟢 good (just improved) | pull-based, wired, tiered, full list |
| Persona | 🟢 good | character→prompt + live signature reload |
| Permissions/safety | 🟢 good (some dead helpers) | tiers + policy + grants enforce |
| Self-improvement | 🟢 good (missing the loop-back) | smoke + benchmark + rollback |
| Model/inference | 🟡 works, misleading config | format decides engine, not the Literal |
| Memory | 🟡 works, half-wired | semantic search live; vec KNN dormant |
| Voice | 🟡 works, config not fully wired | STT→brain→TTS live; some fields ignored |
| Transport/bus | 🟡 in-proc live, rest dormant | multiprocess/ZMQ "not yet operational" |

## 🟢 Solid (wired + working)
- **Agent turn loop** — `run_for_voice → _run_turn → JaegerAgent.run_turn`
  format→call→parse→dispatch loop is live; `/sense/tool·activity·agent_state`
  events fire.
- **Skill discovery** — now pull-based (lean hint → full enriched `skill(list)` →
  tier/fallback → `view`), wired into the real system prompt. *Just improved.*
- **Persona** — character.yaml → short brief → `build_system_prompt`; edits reload
  live via the active-character signature.
- **Permissions** — the 6-tier `@requires_tier` → `PermissionPolicy.check` gate,
  policy modes, per-skill grants, and the credentials/e-stop hard gates all enforce.
- **Self-improvement** — smoke-test gate + scored benchmark + keep-better + curator
  rollback all work.

## 🟡 Incomplete (works, but missing planned pieces)
- **Skill discovery** — the **reflect-check** ("skill existed and was ignored →
  flag") + gap→proposal (P4) not built; `requires_tools` populated only on the
  macOS playbook (sparse elsewhere → `tools` fields mostly empty).
- **Self-improvement** — the *loop-back* is missing: no **gap → propose new skill**
  and no **staleness → auto-retire** proposal (curator assesses but doesn't propose).
- **Voice** — the loop reads `wake_word`/`barge_in`/`self_speech_filter` but
  **ignores `follow_up` / `follow_up_seconds`** (uses a hardcoded 10 s window).

## 🔴 Declared but NOT live (dormant / dead code)
- **Transport multiprocess** — the ZMQ XSUB/XPUB broker path is **"not yet
  operational"** (`launch.py --multiprocess` prints so, returns 2); `get_bus()`
  always returns `InProcBus`. The whole ZMQ stack is present-but-dormant.
- **Memory sqlite-vec KNN** — the extension loads (`_try_load_vec`) but
  `search_memory` only runs a Python-side cosine scan; **no SQL KNN path**.
- **Permissions introspection** — `get_tier` / `is_tier_decorated` have **no live
  caller** (a "future static AST scan"); `ConfirmationRequired` is defined/exported
  but **never raised**.
- **Voice topics** — `/sense/audio_in` is declared with **no producer/consumer**;
  `/act/audio_out` **may not ride the bus** in monolithic mode (Kokoro plays to the
  device directly). Treat those topic rows as schema-declared, not live hops.
- **Avatar frame stream** — `topics.AvatarFrame` / `SENSE_AVATAR_FRAME` are
  **phantom** (publish is swallowed by a bare except); no live avatar frame stream
  today (the orb uses the static card / proxy). *(Found earlier this session.)*
- **`memory/facts.py`** — a JSON-backed Lilith port, **not** on the live recall path.

## ⚠️ Issues / inconsistencies (misleading or debt)
- **Model backend config is inert** — `Config.model.backend` (the
  `llama_cpp_python`/`mlx_lm` Literal) **does not drive dispatch**; the engine is
  chosen from the on-disk model *format* + `runtime.gguf_engine`/`mlx_engine`. The
  Literal is "config-visible" only — misleading for anyone editing it.
- **Two parallel Bus stacks** — `transport/*` (msgspec-typed, has `request()`) and
  `app/bus/*` (dataclass + `MessageRegistry`, no `request()`), non-shared, different
  endpoints/env vars. Architectural duplication.
- **Agent-path migration flag** — `JAEGER_USE_NEW_AGENT` docstring says "off by
  default" yet the `JaegerAgent` path is driven unconditionally. Unclear which path
  is canonical; the migration is mid-flight.
- **Skill folder naming** — `computer_use_v1` / `macos_computer_v1` carry `_v1` in
  the folder (duplicating the manifest version); the "computer" family (2 tool-skills
  + the `apple/macos-computer-use` playbook) overlaps confusingly. → **P5 cleanup.**

## Suggested focus order (future)
1. **Skill P4** — reflect-check + gap→proposal (closes reinvent-the-wheel; makes
   pull safe). Highest leverage.
2. **P5 skill cleanup** — rename `_v1` folders, de-overload the computer naming.
3. **Populate `requires_tools`** across SKILL.md (fills the routing `tools` field).
4. **Decide the dormant/dead code** — either wire or delete: sqlite-vec KNN, the
   permission AST-scan helpers + `ConfirmationRequired`, `/sense/audio_in`,
   `memory/facts.py`, the phantom `AvatarFrame`. (Pre-1.0: lean toward deleting
   what isn't on a near-term roadmap — dead code reads as working.)
5. **Fix the misleading config** — make `Config.model.backend` actually select the
   engine, or drop it and document that format decides.
6. **Voice config** — wire `follow_up`/`follow_up_seconds` (or remove the fields).
7. **Bus consolidation** — pick one Bus stack (`transport/*` vs `app/bus/*`) pre-1.0.
8. **Resolve the agent-path migration** — make `JAEGER_USE_NEW_AGENT` truthful or retire it.

> Skill-pipeline items (P1–P7) are tracked in detail in
> `dev/docs/agentic_skill_pipeline_backlog.md`. This doc is the broader,
> all-pipelines health view.
