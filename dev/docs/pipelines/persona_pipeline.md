# Pipeline: Persona (character → system prompt)

**What it is:** how the agent's *character* (Lilith, Jarvis, …) becomes the
system prompt it runs on, how the active character is chosen, and how a change
takes effect live. Verified in code; cite the source before changing.

## Model
A **character** = a `Personality` + identity + assets (`personality/character.py`
`Character`). On disk: `characters/<id>/character.yaml` (identity · prompt · traits
· lore) + `card.png` + `assets/`. Traits are four layers — `hexaco · special ·
expression · domains` — floats 0–1 (`personality/schema.py`).

Two selections, distinct:
- **active** — the character the instance is *playing right now*
  (`set_active_character` → `<instance>/active_character`). Session-level.
- **bound / default** — the canonical character (`bind_character` → `manifest.json`;
  also sets active). The persistent identity.

## Character → prompt

```
character.yaml ──load_character──► Character(personality, role, soul, backstory, …)
        │
   assemble the LIVE system prompt (a SHORT brief, not the full lore):
     • identity_block()   → "You are <name>. <role>."          (character.py)
     • compose_block(p)   → core directive + traits            (personality/compose.py)
     • soul_block()       → the soul narrative                 (character.py)
        │
   build_system_prompt(layout)  → the agent's system prompt     (agent/prompts.py)
```

Note: `Character.prompt()` returns the **full** in-depth persona (directive +
soul + all lore) — that's for the **Studio profile**, NOT the live model. The live
turn uses the short brief above (identity + traits + soul) to keep turns lean; the
rich lore (ideals/mannerisms/quotes/backstory) stays on the sheet for display/future.

## Live reload (change takes effect without a restart)
- `active_character_signature(instance_root)` = `f"{id}:{mtime}"` — changes when the
  character **switches** OR its **traits/profile are edited** (revision bump).
- The agent loop compares it each turn (`main.py :: _refresh_character_prompt`); on
  mismatch it rebuilds the system prompt via `build_system_prompt(layout)` and
  swaps it in — **next turn uses the new persona**.
- Identity edits (name/role in `identity.yaml`) reload via `refresh_identity()`
  (`main.py`), called by self-modifying tools.

## Key functions (`personality/character.py` unless noted)
- Load: `load_character(folder)`, `list_characters()`, `characters_root()`.
- Active/bound: `active_character(root)`, `active_character_id`, `bound_character_id`,
  `set_active_character` (session), `bind_character` (canonical + active).
- Signature: `active_character_signature`.
- Edit/persist: `save_character_traits(folder, traits)`,
  `save_character_profile(folder, role=…, soul=…, …)`, `icon_path()`, `card_path()`.
- Prompt fragments: `identity_block`, `soul_block`, `prompt` (full);
  `personality/compose.py :: compose_block`.

## Surfaces that use this
- **Settings HUD** (PySide6 `agent_settings`, Swift `AgentSettingsHUD` via the
  bridge query/command API) — reads/writes character profile, traits, select/
  make-default.
- **Tray / avatar / chat** — display name + icon come from the active character
  (`resolve_character(ctx)`; the `jaeger bridge` `ready` frame carries name + icon
  for the Swift app).

## Related
- Character bundle / Studio ownership split: `project-studio-jros-ownership-split`
  (memory) — Studio authors + sends a self-contained character bundle; JROS owns
  the runtime.
