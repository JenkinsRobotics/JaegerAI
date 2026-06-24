# JROS skill tree — XP-driven progression for every node + skill

**Status:** foundation document, operator-locked 2026-06-08
**Why this exists:** JROS isn't a static agent framework like Hermes or
ROS.  It's an embodied, continuously-evolving system.  Every skill +
node is meant to grow over time: more capable implementations, more
prerequisites unlocked, more XP earned through use.  This doc is the
contract that pattern obeys.

## The core idea

Every skill / node has:

1. **A level (integer).**  L1 = simplest viable implementation.  Higher
   = more capable.  The skill RUNS at whatever level is currently
   unlocked + active.
2. **XP (integer).**  Accumulates from real-world use.  When XP
   crosses a threshold, the skill levels up (capability improves).
3. **Prerequisites (list).**  Other skill IDs that must be unlocked
   before this skill becomes available.  Forms a DAG, not a pure tree
   — a skill can have multiple parents.
4. **Unlocks (list).**  Other skills this one enables when its mastery
   threshold is hit.
5. **Status.**  `locked` → `available` → `active` → `mastered`.

```
locked       prerequisites not met yet — skill is invisible
available    prerequisites met; not yet used by the operator
active       in use; gaining XP
mastered     reached mastery threshold; unlocks its children
```

## Why XP + levels, not just config flags

A boolean toggle ("enable webrtc_vad: true") expresses NOTHING about
progress.  A level + XP expresses:

- **How far along is this skill?**  L1 vs L4 says volumes.
- **How much is it being used?**  XP rises with successful
  invocations; a stale skill plateaus.
- **What's next?**  The tree exposes the path forward.
- **Operator engagement.**  Eventually a Skyrim-style visualisation
  shows the operator their agent's growth — a personality + skill
  graph that's both motivational and informative.

This is what makes JROS feel like an evolving system rather than a
fixed product.  Operators don't toggle features; they cultivate them.

## Data model

```python
# jaeger_os/skill_tree/schema.py — msgspec.Struct types

class SkillNode(Struct):
    id: str                       # "animation.gif" / "voice.lip_sync"
    name: str                     # human-readable
    description: str
    category: str                 # "animation" | "voice" | "vision" | etc.
    level: int = 1
    max_level: int = 1            # the highest level this skill can reach
    xp: int = 0
    xp_to_next_level: int = 100
    xp_to_mastery: int = 1000
    prerequisites: tuple[str, ...] = ()
    unlocks: tuple[str, ...] = ()
    status: str = "locked"        # locked|available|active|mastered
    schema_version: int = 1       # bumps when the schema changes


class XpAward(Struct):
    skill_id: str
    amount: int
    reason: str                   # "tool_call_success" / "bench_pass" / etc.
    metadata: dict = msgspec.field(default_factory=dict)
    awarded_at_ns: int = msgspec.field(default_factory=time.time_ns)


class SkillTree(Struct):
    schema_version: int = 1
    skills: dict[str, SkillNode] = msgspec.field(default_factory=dict)
    instance_id: str = ""
```

## Persistence

```
<instance>/skill_tree.json     # SkillTree state — XP, levels, status
<instance>/skill_tree.log      # XpAward event log (append-only, JSONL)
```

Same per-instance convention as `<instance>/memory/`,
`<instance>/skills/`.  The JSON file is rewritten atomically.  The
log is for replay / audit / future visualisation.

## Bus integration — XP as a first-class event

```
/sense/xp_awarded     XpAward      ← new topic, every XP grant fires
/sense/skill_level_up { skill_id, new_level }   ← when a skill levels
/sense/skill_mastered { skill_id }              ← when mastery hit
/sense/skill_unlocked { skill_id }              ← when prerequisites done
```

Anything can subscribe — the eventual Swift visualisation reads these
to animate the operator's agent growing.  The TUI status bar can
surface "Animation gained 2 XP" in a corner.  Bench harness can
attribute XP per-case.

## How skills earn XP

Configured per-skill in its metadata (see "Skill manifest" below).
Common patterns:

- **Tool-call XP**: every successful tool dispatch awards N XP to its
  underlying skill.  `text_to_speech` tool → `voice.tts` skill +1 XP.
- **Bench XP**: a passed bench case awards M XP to the skill cluster
  it exercises (`bench:multistep` → multistep skill +10 XP).
- **Milestone XP**: hitting specific markers (first tool use, 100 tool
  uses, surviving a stress test) awards large discrete amounts.
- **Operator XP**: explicit "good response" feedback awards XP
  (future).
- **Time-in-use XP**: a skill that's been active for N hours awards
  a sustain bonus (low rate, prevents fully-stale skills).

XP rates are intentionally TUNABLE per skill.  A safety-critical
skill (motor_command) might have HIGH XP-to-mastery so it requires
extensive proven use.  An aesthetic skill (animation.gif) might
mastery-out fast.

## Per-skill manifest — extending the v3 manifest

Existing skill v3 manifests at `dev/docs/skill_template/SKILL.md`
get extended:

```yaml
# skill manifest (v3 + skill-tree fields)
id: animation.gif
name: GIF animation
description: Plays animated GIF/APNG assets with loop control.
category: animation
schema_version: 3

# Skill-tree (new in 0.5)
level: 1
max_level: 1                # GIFs don't really have higher levels;
                            # next progression is the NEXT skill
xp_to_next_level: null      # no level-up; uses go to xp_to_mastery
xp_to_mastery: 500
prerequisites:
  - animation.sprite        # sprite must be available first
unlocks:
  - animation.video         # mastering gif unlocks video
xp_sources:
  - reason: tool_call_success
    amount: 2
  - reason: milestone:first_play
    amount: 50
```

When the existing skill registry loads a manifest, it constructs a
`SkillNode` from these fields.

## Initial catalog — retro-document existing skills at L1

When the skill-tree module loads on first boot of an instance, it:

1. Walks the registered tool registry.
2. For each tool with a known category, creates a `SkillNode` at
   level 1, status `available`.
3. Loads any persisted state from `<instance>/skill_tree.json`.
4. Reconciles: new tools become new SkillNodes; removed tools are
   archived (not deleted — XP history matters).

The 0.5.0 ship includes a starter tree covering:

- **animation** — image, bitmap, sprite, gif, video, math (L1-L4 from Mochi)
- **voice** — tts (Kokoro), stt (Whisper), gate, mic-pause, barge-in, lip-sync
- **vision** — camera_frame capture, future analysis (rooted but locked)
- **motor**, **light** — Protocols only; locked until JP01 wires
- **core** — file IO, memory, web search, calculate, schedule, time,
  weather (existing — get retro-tagged at L1)

## Visualisation — eventual, not 0.5.0

The operator's vision:

> "i want a visualization of the agent... with a video game aesthetic
> where u can see personality graph, skill tree etc..."

Not in 0.5.0.  But the FOUNDATION that visualisation consumes lands
in 0.5.0:

- The data model is JSON-readable + bus-observable
- The XP log is append-only + replayable
- The personality module (Track B in ROADMAP_0.5) exposes the same
  on-disk pattern — the visualisation reads both for an "agent
  character sheet" view

When the visualisation lands (likely the Swift app's main display
area or a dedicated panel), it has a stable contract to read.

## Evolution discipline (anti-patterns)

* **DON'T** hard-code skill IDs in agent prompts.  The agent uses
  TOOLS; the skill-tree just observes tool dispatch.
* **DON'T** gate user-facing features behind XP.  Skills enabling
  more advanced implementations is fine; refusing to do something
  basic because XP is too low is bad UX.  XP unlocks BETTER, never
  blocks.
* **DON'T** invent skill nodes the agent has no way to use.  Every
  skill is grounded in a real tool / node / pipeline.
* **DO** preserve XP across versions.  A `schema_version` bump is
  the only excuse to reset.
* **DO** keep XP rates tunable per skill — operators tune their
  agent's evolution rhythm.

## Implementation order for 0.5.0

1. `jaeger_os/skill_tree/schema.py` — msgspec.Struct types
2. `jaeger_os/skill_tree/registry.py` — load/save + runtime API
3. `jaeger_os/skill_tree/xp_emitter.py` — bus subscriber that
   converts tool-dispatch events to `XpAward` events on
   `/sense/xp_awarded`
4. `jaeger_os/topics.py` — add `XpAward` + level-up/unlock/mastery
   events
5. Per-node skill manifest extension (animation node first)
6. Initial catalog seeded from current tools
7. Bench harness emits XP per-case-pass (low priority, can ship
   after foundation)

Foundation is small (~500 LOC) but load-bearing.  Tests cover:
load/save round-trip, prerequisite cascade, level-up threshold,
schema migration.
