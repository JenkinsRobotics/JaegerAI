<!--
This README documents the persona framework as it lands in 0.3.0.
Per the 0.3.0 plan ([[odysseus_review_and_0.3.0_plan]] §1.2), the
full "Persona Pack" catalogue with character levels, skill bundles,
and tool gates is deferred to the Lilith-AI development line.  What
0.3.0 ships is the *general framework*: a simple template-prefill
flow for the existing identity.yaml + soul.md initialisation step.
-->

# Personas — wizard prefill templates

A **persona** is a YAML template the setup wizard can use to *prefill*
the identity questions (name / role / personality / voice) and the
initial `soul.md` body.  Picking one is optional; the wizard still
asks every question and the operator can edit any prefilled answer
before it's written.

## Zero runtime cost

Personas exist **only at wizard time**.  After setup completes, the
instance directory contains a plain `identity.yaml` + `soul.md` with
the operator-confirmed values.  Nothing in the runtime prompt
assembler ([jaeger_os/core/prompts/assemble.py](../core/prompts/assemble.py))
reads from this directory, looks up persona IDs, or loads anything at
turn time.  The prefill literally just hands defaults to the wizard
prompts — same execution path as if the operator had typed the same
strings by hand.

That's why this is safe to ship now without waiting on the bigger
persona-runtime design: it can't slow the agent down because it
isn't on the agent's hot path.

## File format

```yaml
# jaeger_os/personas/<id>.yaml
schema: persona/v1
id: jarvis
name: "Jarvis"
description: >
  One-line summary shown in the wizard's persona picker.
identity:
  display_name: "Jarvis"
  role: "general-purpose agentic assistant"
  personality: "Helpful, capable, concise — honest about uncertainty."
  voice_tone: "clear, even-keeled"
  voice_id: "am_michael"          # optional; omit to let the operator pick
soul_md: |
  ## Who I am
  Multi-line markdown body the wizard writes to soul.md verbatim.
  …
```

Fields:

| Field | Required | Notes |
|---|---|---|
| `schema` | yes | Must be `persona/v1` (forward-compat marker). |
| `id` | yes | Stable short identifier; must match the filename stem. |
| `name` | yes | Human-readable label shown in the wizard. |
| `description` | yes | One line, ≤ 120 chars; shown next to the name. |
| `identity.display_name` | yes | Becomes `identity.name` (≤ 64 chars). |
| `identity.role` | yes | Becomes `identity.role` (≤ 256 chars). |
| `identity.personality` | yes | Becomes `identity.personality` (≤ 2048 chars). |
| `identity.voice_tone` | no | Defaults to `"neutral"` if absent. |
| `identity.voice_id` | no | If present, picks the Kokoro voice automatically; otherwise the wizard still asks. |
| `soul_md` | no | If present, becomes the initial body of `soul.md`. |

## Reserved for Lilith-AI development

The following fields are **intentionally not part of `persona/v1`** —
they get designed and shipped on the Lilith line, not here:

- `character_levels` — tier-gated traits (curious → assertive →
  protective …) that change with time/experience
- `skill_bundles` — automatic enable/disable of skill sets per persona
- `tool_gates` — persona-specific tool allow / deny lists
- `runtime_swap` — switching persona on a live instance without re-setup
- `relationships` — multi-agent persona affinities

Putting these on the Lilith line keeps the agent's hot path
unaffected by the persona framework while the bigger system is
designed.

## Adding a persona

1. Drop `<id>.yaml` into this directory matching the schema above.
2. Validate with `python -c "from jaeger_os.core.instance.personas
   import load_persona; print(load_persona('<id>'))"`.
3. The next time `./run.sh setup` runs, it will appear in the
   persona picker.
