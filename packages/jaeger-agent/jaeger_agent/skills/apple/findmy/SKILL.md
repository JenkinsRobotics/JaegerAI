---
name: findmy
description: Find an Apple device or AirTag on this Mac. Load this for 'where is my
  iPhone / keys / AirTag'. Uses macos-computer-use (computer_do / computer_look) plus
  vision_analyze — never raw osascript loops.
metadata:
  jros:
    tags:
    - findmy
    - airtag
    - location
    - macos
    - apple
    category: desktop
    related_skills:
    - macos-computer-use
    - mac-native
    version: 1.1.0
    platforms:
    - macos
    requires-tools:
    - computer_do
    - computer_look
    - vision_analyze
    - open_on_host
    requires-toolsets:
    - computer_use
---

# FIND MY — native-first

Find My has no CLI. Drive the app with the Mac ladder, then read the
screen. Do not write AppleScript. Do not `every`-query anything.

## SOP

1. `use_skill(name="macos-computer-use")`.
2. `open_on_host(target="FindMy", kind="app")` (or `computer_do` if
   open_on_host cannot classify it).
3. `computer_do(goal="In Find My, show the Devices tab and the location
   of <name>")` — or Items for an AirTag.
4. If the tool result has no address: `computer_look(app="FindMy",
   include_screenshot=True)` then
   `vision_analyze(image_path=<that png>, question="What device/item is
   selected and what location is shown?")`.
5. Report only what the tool/vision returned. Privacy: only devices
   the user owns.

## ERROR HATCH

- Find My not signed in / empty → tell the user; do not invent a pin.
- `needs_permission` → Accessibility and/or Screen Recording; stop.
- `computer_do` cannot drive Find My → one screenshot+vision pass, then
  stop. No click loops. No `osascript` via `terminal`.

## DONE WHEN

The user has a location (or "Find My didn't show one") sourced from
`computer_do` / `computer_look` / `vision_analyze`. Never a fabricated
map pin.
