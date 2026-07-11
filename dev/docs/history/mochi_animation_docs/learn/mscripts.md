# MochiScript (mscripts)

## What it is

Mochi's own scripting DSL for orchestrating multi-step
animations: timing, branching, mode switches, conditional
playback.  Lets one operator-authored file drive a whole
performance.

## History

- Mochi-specific.  Inspired by Fanuc robotics motion programs
  (per the operator's design note) — concise step-by-step DSL
  for sequencing.
- 18 mscript files currently in `assets/mscripts/`
- Operator design note (`docs/future_multi_timeline.md`)
  proposes splitting future mscript work into TWO layers: a
  multi-channel timeline (general-purpose) + mscript itself
  (scoped down to motor / actuator control)

## How it works

Each script is a sequence of commands with timing.  The mscript
engine reads them, schedules them on a wall-clock + frame-clock
basis, and emits the right `mode <name>` / `color <r> <g> <b>`
commands at the right times.

Schedule semantics roughly match Fanuc's TP (Teach Pendant)
programs: ordered steps with optional delays, conditional jumps,
and labelled targets for branching.

## How Mochi implements it

- `nodes/animation/plugin_core/mscript_engine.py` — the script
  interpreter
- `assets/mscripts/*.mscript` — 18 authored sequences
- `tools/mscript_editor_gui.py` — visual editor

## Try it

In the Library, set `TYPE: mscripts` — 18 entries.  Try
`demo_wink.mscript` first (the default script loaded at startup).
Compare playback of an mscript to a single-mode animation: notice
that the mscript can cycle through several other animations as
part of its performance.

## What's coming

`docs/future_multi_timeline.md` captures the operator's intent
to split mscripts:

- The general "multi-channel timeline" (animation + speech +
  motor + light tracks) lives in a future format inspired by
  OTIO / Lottie / MIDI
- mscript becomes the **motor-channel DSL** specifically — its
  Fanuc-style strengths make sense there

That's a follow-up project, not in current scope.
