---
name: macos_computer
version: 1
kind: human_authored
category: cognitive
runtime: in_process
permission_tier: 2                 # EXTERNAL_EFFECT — drives the host UI
embodiment_requires: ["macos"]
authored_at: 2026-05-25
description: macOS-native computer control via a capability ladder — AppleScript → CDP → Accessibility → screenshot. 10-30× faster than the screenshot loop for Mac apps, focus-preserving where possible. The recommended computer-use path on a Jaeger unit running macOS.
registers_tools:
  - computer_do(goal) -> {ok, plan, steps, result}
  - computer_use(action, ...) -> {ok, result}
  - computer_look() -> {ok, app, windows, ax_tree}
tags: [computer-use, macos, desktop, automation, gui]
requires_tools: [computer_do, computer_use, computer_look]
metadata:
  jros:
    related_skills: [computer_use, web-app-qa]
---

# macos_computer — capability-ladder Mac control

## What
Mac-native computer control built around a **capability ladder**:
the planner tries the fastest, most semantic engine first and only
falls back to the screenshot loop when no object-level surface
exists. This is the path Jaeger should reach for on macOS.

```
applescript_engine  →  browser_engine  →  ax_engine  →  vision_engine
       ↑ fastest, app-native            slowest ↑, last resort
```

- **applescript_engine** — per-app dispatch (Calculator, Notes,
  Safari, Mail, Finder, Music, Reminders, Messages; document
  creation in TextEdit / Pages / Keynote / Numbers / Word /
  PowerPoint / Excel via `new_doc` / `new_presentation` /
  `new_workbook` + `save_doc`; and window management for ANY app:
  `window_list` / `window_bounds` / `move_window` / `resize_window`
  / `minimize` / `fullscreen` / `zoom_window` / `close_window`).
  When the target app has an AppleScript dictionary, this engine
  runs the action with one OSAscript round-trip — no pointer
  movement, no focus steal. Sandboxed apps (App Store Office) may
  pop a one-time "Grant File Access" dialog on save outside their
  granted folders — prefer ~/Documents.
- **browser_engine** — Chrome DevTools Protocol via the existing
  Playwright surface. For web pages, talk to the DOM directly.
- **ax_engine** — Accessibility API via PyObjC. `AXPress` /
  `AXSetValue` / `AXRaise` / `AXPosition`. Focus-preserving —
  doesn't steal your cursor or front-app. Works for *any* app
  that exposes AX (most do).
- **vision_engine** — Screenshot + element detection. Last resort
  for canvas apps, games, custom UI without AX. Delegates to the
  universal `computer_use` skill.

## When
Use `macos_computer` on a Mac for ANY computer-control task. The
planner picks the right engine; the agent doesn't need to know
which one ran. Use the universal `computer_use` skill only when
testing the portable path or running on a non-Mac host.

Three tools the model sees:

- `computer_do(goal)` — natural language goal; planner expands it
  into a step list and dispatches each step through the ladder.
  E.g. ``computer_do("open Calculator and compute 5 plus 5")``.
- `computer_use(action, ...)` — explicit primitive (open, click,
  type, read, screenshot) when the planner's intent inference
  isn't right.
- `computer_look()` — current screen state. Returns the frontmost
  app, window list, and the AX tree of the focused window. Cheap;
  doesn't take a screenshot unless asked.

## How
- Tier-2 (EXTERNAL_EFFECT) — confirmation-gated. The user approves
  before the agent drives the UI.
- Per-engine availability: each engine's `is_available()` reports
  back. `applescript_engine` checks `osascript`; `ax_engine`
  checks PyObjC + Accessibility permission; `browser_engine`
  checks Playwright; `vision_engine` always returns True.
- The planner records which engine handled each step so
  ``computer_do(...)["steps"]`` is auditable.

## Depends on
- macOS (PyObjC for AX, osascript for AppleScript).
- Accessibility permission for the host process (Terminal, IDE).
- Screen Recording permission only when the vision fallback fires.
- Optional: Playwright (browser_engine — already a JROS dep).
