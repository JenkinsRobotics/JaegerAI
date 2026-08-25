---
name: humanizer
description: "Edit supplied prose to reduce generic AI-writing patterns while preserving the author's meaning and voice. Use when the user asks to humanize, de-slop, or make text sound more natural."
license: MIT
metadata:
  jros:
    version: 3.0.0
    lifecycle: optional
    skill-class: first-class
    platforms: [linux, macos, windows]
    requires-tools: [read_file, patch, write_file]
    tags: [editing, prose, voice, humanize]
    category: creative
---

# HUMANIZE PROSE

## SOP

1. Read the complete source and identify audience, purpose, and existing voice.
2. Preserve facts, claims, citations, technical terms, and intentional quirks.
3. Remove only demonstrated problems: canned openings, repetition, inflated
   abstraction, excessive symmetry, fake quotations, filler, and uniform rhythm.
4. Read the relevant pattern sections in `references/imported-guide.md` when a
   passage needs diagnosis; do not mechanically apply every pattern.
5. Rewrite at the requested level and compare meaning paragraph by paragraph.
6. Return the revision; summarize material editorial changes only if useful.

## ERROR HATCH

If the intended voice or audience is unknown, make conservative edits. Never add
personal anecdotes, experience, citations, or facts the author did not provide.

## DONE WHEN

The revised text preserves meaning and evidence, sounds less formulaic, and does
not fabricate a human identity or claim authorship history.
