# Mochi animation review (2026-06-10)

**Reviewer:** Claude
**Scope:** post-reorg state of Mochi — what works, what's missing, what to build first.

## The headline finding

> **The LLM doesn't drive animations today.**  It chats; the animation
> node renders whatever the GUI tells it.  The two run in parallel
> without coordination.

Topic surface today:

```
LLM subscribes:    ext.stt.text, stt.text
LLM publishes:     ext.llm.reply, llm.reply
Animation ctrl:    GUI/CLI → animation node (mode/play/stop/size/color)
                   No bus subscription to llm.reply.
```

So when the LLM says *"I feel happy!"* the animation node never sees
that and never picks a happy clip.  The product promise (an LLM that
chooses contextual animations) is **aspirational**, not implemented.

## What's already strong

| Area | Notes |
|---|---|
| Renderer pipeline | `nodes/animation/` ships 7 handler types (image, bitmap, sprite, gif, video, math, mscript).  Mature and battle-tested. |
| Bus + node infra | `transport/` has a real ZMQ broker, node base class, topic conventions.  Multi-process from day one. |
| Asset library | **261 assets** across gifs (71), videos (65), math (26), mscripts (18), animations (6 eye states), png (8), bitmap (5), procedural (1). |
| Plugin spec | `core/plugin_registry.py` cleanly loads agent + nodes as subprocesses. |
| GUI tooling | mochi_studio + mscript editor + bitmap editor + sprite editor + Qt vdisplay.  Operator can author content. |

## What's missing (in priority order)

### Tier 1 — load-bearing (without these, LLM can't drive animations)

| # | Gap | Why blocking |
|---|---|---|
| 1 | **Animation catalog** with name + type + path + tags + when-to-use hints | LLM can't pick from a list it doesn't have.  Filenames alone (`ChasmDaltynPunch.gif`) carry no mood/use-case info. |
| 2 | **LLM tool-call protocol** — a way for the LLM to say "play X" | Today the LLM only emits free text.  No structured channel for action commands. |
| 3 | **Animation node subscription to LLM commands** | Even if the LLM emits "play happy_blink", nothing listens. |
| 4 | **Animation-aware system prompt** | Today: *"You are Mochi, a cheerful assistant who speaks concisely."*  Tells the LLM nothing about its job. |

### Tier 2 — quality + iteration speed

| # | Gap | Why valuable |
|---|---|---|
| 5 | **Per-asset metadata** (mood, category, duration, energy level) | Currently filenames have to carry all meaning.  Curated metadata makes selection accurate + fine-tune training tractable. |
| 6 | **"Dry-run selector" CLI** — feed a prompt, print which animation the LLM would pick + why | Fast prompt-tuning feedback loop without running the full bus. |
| 7 | **Two-personality split** — the chatty face vs. the animator are different concerns; today one LLM does both | Cleaner prompts, easier fine-tuning, lets each be tuned independently. |
| 8 | **Per-emotion default mappings** — happy → set of clips, sleeping → set of clips, etc. | LLM picks the emotion; default mapping picks a clip.  Faster than full LLM selection on every turn. |

### Tier 3 — fine-tuning prep

| # | Gap | Why eventually load-bearing |
|---|---|---|
| 9 | **Selection log** — record every (context → picked animation) pair | Becomes the fine-tune dataset.  Without logging, no training data. |
| 10 | **Evaluation harness** — for a set of contexts, is the chosen animation "appropriate"? | Lets fine-tunes be benchmarked rather than vibed. |
| 11 | **Level taxonomy** — JROS adopted L1-L6 (static → sprite → gif → math → rigged → generative).  Mochi could surface the same. | Operator + LLM both reason about animation level constraints. |
| 12 | **Curated subset** — pull the "good ones" out of the 261 assets into a starter pack the LLM definitely knows. | More than 261 options paralyses the LLM.  ~20-30 curated clips with rich metadata beats 261 unlabeled. |

## What I'd ship first (this commit)

**The animation catalog** (Tier 1 item #1).  It's the foundation for items
2-4 and is independently useful for the GUI / CLI / fine-tune dataset.

A `tools/build_catalog.py` walks `assets/` and produces a JSON file
with one entry per renderable asset:

```json
{
  "name": "happy_blink",
  "type": "animations",
  "path": "assets/animations/happy_blink.json",
  "category": "eye_animation",
  "mood": "happy",
  "tags": ["eye", "blink", "happy"],
  "size_hint": null,
  "duration_ms": null
}
```

Mood + tags are auto-derived from the filename and asset directory.  The
catalog is regenerated on demand; operator can hand-edit overrides
into a sidecar (followup).

Once the catalog exists, downstream work becomes mechanical:

- LLM prompt gets the catalog
- LLM emits `<play name="X"/>` tags in its reply
- Animation node subscribes to `llm.reply`, parses tags, dispatches
  to the play handler
- All on the existing bus, no new infrastructure

## Proposed work order

```
Commit  N      catalog generator + first catalog              (this PR)
Commit  N+1    LLM <play> tag protocol + animation node parser
Commit  N+2    System prompt update — LLM knows about catalog
Commit  N+3    Dry-run selector CLI for prompt tuning
Commit  N+4    Per-asset metadata sidecar — operator-curated tags
Commit  N+5    Selection log → fine-tune dataset prep
Commit  N+6    Two-personality split (chat vs. animate)
Commit  N+7    Evaluation harness — does the LLM pick appropriately?
```

Once N+7 lands, Mochi is genuinely "an LLM that picks animations" and
the fine-tune work has data to learn from.

## Out of scope here

- New animation handlers (the 7 existing cover the design)
- Renderer perf work (current pipeline is healthy)
- mscript rework (operator's multi-channel-timeline idea is captured at
  `docs/future_multi_timeline.md`; that's a separate track)
- Avatar hardware integration (Dasai Mochi3 device)
