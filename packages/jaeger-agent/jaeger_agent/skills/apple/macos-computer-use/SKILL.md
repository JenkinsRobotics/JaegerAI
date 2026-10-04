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

## IDE AGENTS AND MESSAGING

Treat IDE UI control and agent delegation as different transports:

1. Use `computer_look(app="<IDE name>")` to inspect an IDE panel and
   `computer_do(goal="...")` for a bounded native UI action.
2. Do not click into an agent chat box and type a prompt when Jaeger's
   structured delegation transport can carry the message.
3. Send a fresh message to an extension-agent runtime with
   `delegate_task(goal="...", runtime="codex|claude|gemini")`. Use
   `list_delegates` first when availability is uncertain.
4. Preserve the returned `task_id`, runtime, status, and reply as delegation
   evidence. A successful call returns the worker's reply in `summary`.
5. CLI delegates are currently one-shot. Do not claim that a reply came from
   an already-open IDE-panel conversation, or that a follow-up reused that
   conversation, unless the selected transport advertises
   `existing_conversation` and `follow_up`.

Use GUI interaction only when the user's intended result is itself a visible
IDE state change, or when no structured agent transport exists. After a GUI
action, inspect the target again before reporting success.

## ERROR HATCH

Missing permission or ambiguous screen target: report it and stop. Do not click
coordinates based on stale screenshots.

## DONE WHEN

The requested visible state is verified by the tool or screenshot result.
