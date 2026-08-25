---
name: apple-reminders
description: Add, list, or complete Apple Reminders (Reminders.app, iCloud) via remindctl.
  Load this for 'add a reminder that syncs to my iPhone', 'what's due today in Reminders'.
  Agent alerts ('nudge me in 10 minutes') use scheduling / schedule_prompt instead.
metadata:
  jros:
    tags:
    - reminders
    - apple
    - macos
    - icloud
    - todo
    category: desktop
    related_skills:
    - scheduling
    - apple-notes
    - mac-native
    - calendar
    version: 1.1.0
    platforms:
    - macos
    requires-tools:
    - terminal
---

# APPLE REMINDERS — remindctl

Reminders.app via `remindctl`. Syncs to iPhone/iPad. Call through
`terminal`. This is NOT the agent scheduler.

## WHEN NOT

- "Remind me in 10 minutes" (agent speaks later) → `scheduling` /
  `schedule_prompt`.
- Calendar events → `mac-native` `create_event`.
- Project boards → `kanban`.

## PREREQUISITES

- `brew install steipete/tap/remindctl`
- `terminal(command="remindctl status")` then `remindctl authorize` if needed

## TOOLS (exact)

```
terminal(command="remindctl today --json")
terminal(command="remindctl overdue --json")
terminal(command="remindctl list")
terminal(command="remindctl add --title \"Call mom\" --list Personal --due tomorrow")
terminal(command="remindctl complete <id>")
```

`--due` accepts `today`, `tomorrow`, `YYYY-MM-DD`, `YYYY-MM-DD HH:mm`.

## SOP

1. Clarify Apple Reminders (syncs to phone) vs agent `schedule_prompt`.
2. `remindctl today --json` / `remindctl list` before adding a duplicate.
3. Confirm title + due date, then `remindctl add ...`.
4. Complete by id from the JSON list — never guess ids.

## ERROR HATCH

- command not found → brew install; stop.
- not authorized → `remindctl authorize`; do not retry add.
- "remind me" was an agent alert → switch to `schedule_prompt`, do not
  create a Reminders.app item.

## DONE WHEN

`remindctl --json` shows the item (or the completion). Never claim a
reminder is on the iPhone without that result.
