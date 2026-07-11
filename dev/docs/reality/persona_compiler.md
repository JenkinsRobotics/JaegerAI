# Persona Compiler — State/View for the character layer

Status: **compiler + WORKERS-RUN-VANILLA shipped** (2026-07-02).
Architecture MEASURED: single-pass boundary disproven → persona removed from the
worker prompt entirely (no `character` fragment; sub-agents already clean). The
compiled View (`Character.character_block()`) is retained to feed the **two-pass
output filter** (re-voices the final reply) — that filter stage is the next
sprint (TODO), tracked below.

## Problem

The character reaches the model as three separate prompt fragments —
`identity` (86 chars), `soul`, and `personality` (~1788 chars, mostly numeric
HEXACO/SPECIAL/Expression sliders). Two issues:

1. **Fragmented + redundant.** The `identity` one-liner ("You are Anakin
   Skywalker, the Chosen One…") is restated verbatim at the top of the
   `personality` block's description. Three headers for one character.
2. **Raw sliders are inert on off-the-shelf models.** A base 4B model has never
   been trained on our scale, so `sarcasm: 0.40` is just tokens it can't map to
   behavior — pure bloat today. (The numbers matter *long-term* as fine-tuning
   labels; see "Deferred".)
3. **Persona bleed risk.** Character traits sitting in the execution context can
   drift tool params / PLAN lines / code toward "in-character" instead of cold
   and literal — working against the rigid execution loop we just locked in.

## Design: State vs View

**State** = the numeric personality (floats + dicts). Stays in the backend
exactly as-is. Source of truth. The fine-tuning enabler. The model never sees it.

**View** = a compiled natural-language block. The *only* thing the model sees.

### The compiler (compile on *change*, not per turn)

When a character is created/edited — or the agent self-adjusts a slider — the
View is (re)compiled; the model only ever sees compiled prose, never raw floats.

**Implementation note:** we get compile-on-change *for free* from the existing
prompt cache, so there is no persisted `compiled_view` field (no migration, no
drift). The assembled system prompt is cached in `main.py` and rebuilt only when
`active_character_signature` (character id + sheet mtime) changes — see
`_refresh_character_prompt`. So `Character.character_block()` compiles from State,
and because assembly is signature-gated it runs on an actual edit, not per turn.
The compiled View is inspectable any time via `jaeger prompt`.

Compiler rules:
- Bucket each slider Low (<0.3) / Mid (0.3–0.6) / High (>0.6).
- **Only surface deviations.** Mid-band emits nothing — neutral is the default.
  A character with 3 strong traits gets 3 clauses, not a 12-line dump.
- Map each deviation to a short behavioral clause
  (e.g. `sarcasm>0.7` → "use heavy sarcasm and biting wit";
  `formality<0.3` → "speak casually, skip polite convention").
- State is truth: recompiling on save **overwrites** the cached View. No
  manual-override field yet (YAGNI — add only if a real need appears).

## The unified character View (built, then routed to the filter)

> Note: we first replaced the three fragments with one `character` prompt
> fragment. The A/B/C bench (below) then proved persona-in-worker taxes the 4B,
> so the fragment was **removed from prompt assembly** — the worker runs vanilla.
> The compiled block below is now produced by `Character.character_block()` for
> the **output filter**, not injected into the prompt. Layout is unchanged:

The unified block (one coherent View):

```
## My voice — <name>
<identity line + soul narrative, deduped>
<compiled trait clauses — deviations only>

THE PERSONA BOUNDARY: this voice governs ONLY prose I address to the operator.
When I write a PLAN line, call a tool, fill a tool parameter, or write code, I
am Jaeger OS — cold, precise, literal. Persona never enters execution.
```

### Sub-agents get no character at all

A sub-agent's `subagent_preamble` ("you are a focused sub-agent…") is its whole
identity. It returns data to the *parent*, not the user, so it needs no voice.
Today `identity` leaks into sub-agents (gated `_all`); this removes that.

## assemble.py changes (final: worker vanilla)

- Delete fragments `identity` (`_all`), `soul` (`_non_subagent`),
  `personality` (`_non_subagent`).
- **No character/persona fragment at all** — the worker prompt carries none.
  (An intermediate `character` fragment existed; the bench removed it.)
- `Character.character_block()` stays as the compiled View, consumed by the
  two-pass output filter (response path), not prompt assembly.

## Architecture choice: MEASURED → two-pass output filter

We first tried single-pass with a boundary rule (keep persona in context, tell
the model to firewall it). **The bench disproved it.** On E4B the persona taxes
execution ~7%, and the boundary does not hold at any persona size:

| Arm | Persona in worker context | Score (81 cases) |
|-----|---------------------------|------------------|
| C — vanilla (no persona)   | 0 chars     | **75.5** (76, 75) |
| B-lite — voice tag only    | 594 chars   | 70 |
| A — old numeric sliders    | 1788 chars  | 70 |
| B — compiled boundary      | 1115 chars  | **68** (68, 68) |

Monotonic: more persona in context → worse execution, across recovery / files /
skill / routing (the bleed fingerprint). Even a 594-char voice tag stays ~5
cases below vanilla. The "drop persona when executing" instruction is not
reliably obeyed by a 4B.

**Decision: persona is an OUTPUT FILTER, not worker context (two-pass).**
- The **worker** (main agent) runs with NO character in context — vanilla, sharp.
  `JROS_NO_PERSONA=1` becomes the effective default for the execution prompt.
- The compiled View (`character_block()`) becomes the **filter prompt**: after
  the agent produces its final user-facing text, a light second pass re-voices
  that text in the character's voice. Facts/values/formatting are preserved;
  only tone changes. Tool outputs and intermediate steps are never filtered.

This is the "character as presentation layer" the design targeted — the bench
just proved the boundary had to be a real pipeline stage, not a prompt rule.
Everything already built (compiler, unified fragment, sub-agent strip) feeds
this: the compiled View is exactly the filter's persona input.

### Two-pass risks to handle in the build
- **Fact fidelity:** the filter MUST preserve numbers, paths, names, code, and
  table structure — re-voice tone only. Prompt it tightly; never let it
  paraphrase a value.
- **Latency/streaming:** stream the *filtered* pass; the worker pass is internal.
  Cost is one extra short generation per user-facing turn (not per tool call).
- **Skip when empty:** no character, or a turn with no user-facing prose (pure
  tool hand-off), skips the filter.

## Bench protocol (how the above was measured)

Full 81-case corpus, E4B. During the experiment, persona was toggled via
temporary env knobs on the `character` fragment (`JROS_NO_PERSONA` → vanilla;
`JROS_PERSONA_LITE` → voice tag only; unset → full View). Those knobs were
one-off measurement scaffolding and have been **removed** now that vanilla is the
shipped default — the results table above is the record.

## Deferred (not in this change)

**Fine-tuning dataset logging.** The long-term goal (train a JROS model on the
sliders) is real, and preserving the numeric State — which we do — is the only
thing needed to keep that door open. Building turn-logging / dataset-curation
infra now is premature (no trainer, no schema, no eval). Handle it in a
dedicated project later, curating from State + existing transcripts, enforcing
the boundary (tool calls = 0% persona) at *that* time.

## Test impact

Four files assert on the old fragment names/content and will be updated:
`test_prompt_identity.py`, `test_prompts.py`, `test_prompt_assembly.py`,
`test_assemble_integration.py`. New: a compiler unit test (buckets →
deviation clauses; mid-band emits nothing) and a sub-agent-has-no-character
assertion.
