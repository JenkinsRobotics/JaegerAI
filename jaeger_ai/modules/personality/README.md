# personality — INCLUDED, not parked

Job: the structured persona Jaeger composes into its system prompt on EVERY turn, so this shapes how Jaeger talks all the time, not occasionally. This is a JaegerAI framework feature, and it stays in the stack.

Correction to the earlier audit: personality was listed as a park candidate because of 14 characters vs one companion identity. The operator corrected that on 2026-10-22: personalities ARE a feature of the framework and should be included. This module records that correction. Do NOT park personality to Desktop.

This module does NOT copy the personality code. Code stays in jaeger_ai/features/personality/, and copying it here would create a second, drifting copy.

Source in this repo:
- jaeger_ai/features/personality/schema.py — trait model: HEXACO / SPECIAL / Expression / Domains + custom_instructions, ranges.
- jaeger_ai/features/personality/character.py (29,178 bytes, 648 lines) — loading a named character, character/v1 package shape (Mochi / JaegerAnimation ecosystem), identity/role/voice, backstory, assets (card/avatar).
- jaeger_ai/features/personality/compose.py (9,627) — turning a persona into the text the model actually reads (narrative, values, behavior, mannerisms, strong trait deviations, NOT a numeric dump).
- jaeger_ai/features/personality/persona_state.py (7,719) — mood and state that shift during a conversation.
- jaeger_ai/features/personality/characters/ — 20 character folders on listing 2026-10-22 (assistant, mochi, jarvis, tars, lilith, glados, hal_9000, bender, anakin_skywalker, eren_yeager, kamina, lelouch, paul_atreides, clanker, helldiver, simon, plus work roles reliability_auditor, research_strategist, robotics_architect, systems_principal), each as editable YAML + card art, character/v1 manifest. Edit a persona without coding: open characters/<name>/ YAML.

Always on: pick a character in instance settings. Check: change a trait, start a new chat, tone shifts.

Overlap with jaeger-agent — checked 2026-10-22, names only, standalone repo:
- jaeger-agent has NO file named personality, and NO character library. Search for "personality" returned 0 matches.
- jaeger-agent DOES have: prompts/persona_lane.py (38,384 bytes, Persona Mode C — id/ego, in-character answer vs delegate via perform_task tool, Lilith example), prompts/persona_filter.py (8,379), prompts/default_persona.py (4,147), tools/persona.py (4,892).
- tools/persona.py is NOT a competing personality system: it IMPORTS from jaeger_ai.features.personality.character (active_character, layer_items) to read/tune the ACTIVE character's HEXACO/SPECIAL/Expression/Domains sliders. That is a consumer of JaegerAI personality, and a seam to note — jaeger-agent's extraction doc says JaegerAgent must never import JaegerAI, yet this tool does. Do NOT "fix" that by editing jaeger-agent (not allowed); record it as a host-seam issue for when jaeger-agent is edited upstream.
- Verdict, per the operator's overlap rule: JaegerAI personality is the BETTER, fuller version (trait model + library + compose + state), so it is the MAIN module, not an optional alternative, and not parked. jaeger-agent persona_lane is a DIFFERENT job (prompt routing: answer in character vs delegate to the clean loop), so keep it in jaeger-agent, do NOT copy it into JaegerAI. If a future JaegerAI prompt-routing module is wanted, it should be a new module that uses the host seam, not a copy of persona_lane.py.

One companion identity vs many characters — how to reconcile, without deleting:
- One identity, same memory, same approval gate, whether talking, running projects, or in a body — that is the companion definition.
- Characters are NOT separate identities: they are editable persona packs (trait + narrative + voice + assets) that the ONE companion can wear, plus work roles (auditor, strategist, architect, principal) that are specialist modes, not separate agents.
- Default should be one companion character (assistant / mochi lineage — confirm which one the operator wants as default, do not assume). The others are optional alternatives, selectable in instance settings, not defaults, and not separate products.

Test to run when code-run is available: change a trait in YAML, start a new chat, tone shifts; switch character, system prompt compose changes, identity/memory/approval gate do not change; read_traits / adjust_trait via the jaeger-agent tool still resolves to the JaegerAI active character (seam check).
