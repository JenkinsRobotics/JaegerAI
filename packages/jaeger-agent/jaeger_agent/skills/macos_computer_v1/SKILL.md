---
name: macos_computer
archived: true
description: "Drive this Mac via the native capability ladder (AppleScript → CDP → Accessibility → screenshot last). Load for any 'do X on my Mac' task. The live SOP is macos-computer-use — this skill registers computer_do / computer_use / computer_look."
version: 2.0.0
kind: human_authored
category: cognitive
runtime: in_process
permission_tier: 2
embodiment_requires: ["macos"]
platforms: [macos]
requires_tools: [computer_do, computer_use, computer_look]
tags: [computer-use, macos, desktop, automation, gui]
metadata:
  jros:
    tags: [computer-use, macos, desktop, automation, gui]
    category: desktop
    related_skills: [macos-computer-use, mac-native, computer_use]
---

# macos_computer — capability-ladder Mac control

The tools live here (`computer_do`, `computer_use`, `computer_look`).
The recipe to pick the right rung lives in `macos-computer-use`.

## SOP

1. `use_skill(name="macos-computer-use")` and follow its native-first
   ladder. Do not skip to the screenshot loop.
2. Plain "open X" → `open_on_host`. In-app action → `computer_do(goal=...)`.
   Dark mode / volume / playback → `mac-native` (`system_control` /
   `media_control`).
3. Screenshot/click (`computer_open_app` / `computer_click`) is LAST
   resort only.

## TOOLS (exact)

```
computer_do(goal="...")                  plan + execute + verify
computer_use(action="...", target="...") one explicit primitive
computer_look(app="Safari")              AX tree / front window, no screenshot
```

## ERROR HATCH

- `needs_permission` → tell the user to grant Accessibility (and Screen
  Recording only if a screenshot is required). Do not retry blindly.
- `computer_do` cannot find an AppleScript/AX path → then the screenshot
  loop is legitimate. Say so.

## DONE WHEN

The requested Mac state is reached and verified with `computer_look` or
the tool's own success payload — never claimed from a guessed click.
