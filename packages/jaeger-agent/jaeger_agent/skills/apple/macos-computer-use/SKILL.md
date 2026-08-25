---
name: macos-computer-use
description: Drive this Mac's GUI to open apps, click, type, select menus, or change
  settings. Use when no dedicated native tool can complete the request; native Accessibility/AppleScript
  paths precede screenshot clicking.
metadata:
  jros:
    version: 4.0.0
    lifecycle: core
    skill-class: first-class
    platforms:
    - macos
    requires-tools:
    - open_on_host
    - computer_do
    - computer_use
    - computer_look
    - computer_open_app
    - computer_read_screen
    - computer_click
    - computer_menu_select
    - computer_type_text
    - computer_press_key
    requires-toolsets:
    - background
    - computer_use
    aliases:
    - macos_computer
    - computer_use
    tags:
    - macos
    - gui
    - accessibility
    - computer-use
    category: apple
    compatibility: Requires macOS; Accessibility or Screen Recording permission may
      be needed.
---

# MACOS COMPUTER USE

## LADDER

1. Dedicated native tool from `mac-native` when one fits.
2. `open_on_host(target=..., kind="app|url|file")` for opening only.
3. `computer_do(goal="...")` for native Accessibility/AppleScript execution.
4. `computer_look(app=..., include_screenshot=true)` to inspect uncertain state.
5. Coordinate screenshot tools only when semantic/native paths cannot identify
   the control. Verify after every action; never run an open-ended click loop.

Read `references/legacy-guide.md` only for detailed ladder/tool examples.

## SOP

1. State the desired end state and choose the highest viable rung.
2. Inspect before destructive or externally visible actions and obtain required
   confirmation immediately before executing them.
3. Execute one bounded action, then inspect the resulting state.
4. Stop after two equivalent failures; do not vary raw AppleScript guesses.

## ERROR HATCH

Missing permission or ambiguous screen target: report it and stop. Do not click
coordinates based on stale screenshots.

## DONE WHEN

The requested visible state is verified by the tool or screenshot result.
