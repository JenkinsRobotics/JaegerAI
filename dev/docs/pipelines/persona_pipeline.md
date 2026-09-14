# Pipeline: character → user-facing voice

**What it is:** how a portable character pack becomes Jaeger AI's user-facing
persona without contaminating the agent's tool arguments, plans, or code.

## Character state

A character is a direct child of `jaeger_ai/characters/` containing a
`character.yaml`. The shared `character/v1` fields carry identity, provenance,
typed assets and an optional render half. Jaeger AI adds `traits`, `level`, and
`revision` for personality compilation and progression.

The Python model lives in `jaeger_ai/characters/character.py`; the normalized
HEXACO, SPECIAL, expression, and domain layers live in
`jaeger_ai/characters/schema.py`.

Two selections remain distinct:

- **Active**: the character this instance plays now, stored in
  `<instance>/active_character`.
- **Bound**: the instance's canonical character in `manifest.json`; rebinding
  also makes it active.

## Runtime flow

```text
character.yaml
    │ load_character()
    ▼
Character + structured traits
    │ character_block()
    ▼
user-facing persona lane / final response filter
    │
    ├── ordinary conversational turn: answer directly in character
    └── tool task: perform_task(request) runs the clean JaegerAgent loop
                                   │
                                   ▼
                         literal tools, plans and code
                                   │
                                   ▼
                          final answer re-voiced once
```

The JaegerAgent worker prompt is deliberately persona-free. Numeric traits are
compiled to behavioral prose only for the user-facing voice. Rich lore remains
available to character interfaces without being dumped into every worker turn.

## Live updates

`active_character_signature(instance_root)` combines the active identifier and
manifest modification time. Selection or profile edits therefore take effect
on the next turn without reloading model weights.

## Main functions

- Loading/library: `load_character`, `list_characters`, `characters_root`.
- Active/bound state: `active_character`, `active_character_id`,
  `bound_character_id`, `set_active_character`, `bind_character`.
- Editing: `save_character_profile`, `save_character_traits`.
- Presentation: `character_block`, `prompt`, `icon_path`, `card_path`.
- Trait prose: `jaeger_ai/characters/compose.py`.

The PySide6 and Swift settings surfaces use the same bridge commands for
selection and edits. Tray, chat, and avatar surfaces resolve the same active
character and card; there is no second UI-only character registry.
