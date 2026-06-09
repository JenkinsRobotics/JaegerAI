---
name: computer_use
version: 1
kind: human_authored
category: cognitive
runtime: in_process
permission_tier: 2                 # EXTERNAL_EFFECT
embodiment_requires: []            # cross-OS — any host with a display
authored_at: 2026-05-20
description: Universal screenshot-based computer control. Works on any host with a display + mouse. Slow but portable. On macOS, prefer the `macos_computer` skill — it uses Accessibility / AppleScript directly and is 10-30× faster.
registers_tools:
  - computer_screenshot(path) -> {ok, path}
  - computer_read_screen() -> {ok, app, window, elements}
  - computer_open_app(name) -> {ok, app}
  - computer_click(x, y) -> {ok, clicked}
  - computer_type_text(text) -> {ok, typed}
  - computer_press_key(key) -> {ok, pressed}
  - computer_menu_select(menu, item) -> {ok, selected}
---

# computer_use — universal screenshot path

## What
Universal cross-OS computer control via the **screenshot loop**: take a
picture of the screen, find a target visually, click coordinates, take
another picture, verify. Works on any host with a display + mouse;
matches the pattern hermes-agent uses by default.

This is the **portable fallback**. On macOS, the `macos_computer`
skill bypasses the visual loop entirely — it talks to the
Accessibility tree, AppleScript dictionaries, and CDP — and is
roughly 10-30× faster for the same operation. Use `computer_use`
when:

- Running on a host without an Accessibility / AppleScript surface
  (most Linux desktops, Windows, an embedded Jaeger unit without
  AX bindings).
- Targeting a canvas-style UI (games, custom widgets, image
  viewers) where there IS no semantic object tree to read.
- Verifying a `macos_computer` action when no AX/value query covers
  what the human would visually check.

## When
Trigger when the task needs a UI the agent has no direct API for AND
the platform doesn't expose a faster object-level surface. The loop
is:

1. `computer_open_app` to bring the app up (macOS-specific today;
   future ports add the linux / windows equivalents).
2. `computer_read_screen` for the on-screen elements + a screenshot.
3. `computer_click` / `computer_type_text` / `computer_press_key` to
   act.
4. `computer_read_screen` again to verify.

## How
- Action tools are tier-2 (EXTERNAL_EFFECT) — confirmation-gated. The
  user approves before the agent moves the mouse / types.
- The macOS implementation uses `osascript` + `screencapture` (no pip
  deps). A future cross-OS port would add pyautogui / X11 / Win32.

## Depends on
- A display + an input layer (mouse + keyboard).
- macOS today: `osascript` + `screencapture` (Accessibility +
  Screen Recording permissions).
- Future ports: pluggable per-OS adapter.
