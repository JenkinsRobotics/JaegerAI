---
name: scheduling
description: "Set reminders, timers, and recurring automations with the built-in scheduler: 'remind me in 10 minutes', 'wake me at 7am', 'every Friday check the news'. Load this whenever the user wants ANYTHING to happen later — a one-off reminder, a repeating task, or a scheduled message — instead of saying you can't do timed actions. You can."
version: 1.0.0
platforms: [linux, macos, windows]
requires_tools: [schedule_prompt, list_schedules, cancel_schedule, get_time]
requires_toolsets: [scheduling]
metadata:
  jros:
    tags: [scheduling, reminders, timers, cron, automation, alarms, recurring]
    category: productivity
    related_skills: [memory-keeping]
---

# SCHEDULING — REMINDERS, TIMERS, AND RECURRING TASKS

You CAN do timed and future actions. `schedule_prompt` stores a prompt that
fires later as a fresh turn of YOU — with your voice, tools, and memory. A
"reminder" is just a scheduled prompt that tells future-you what to do.

## THE TOOLS (exact)
```
schedule_prompt(cron_expr="30 7 * * *", prompt="Say: good morning — take your meds", name="meds")
list_schedules()                       every active schedule + its next-run time
cancel_schedule(name="meds")           remove one by name
get_time()                             ALWAYS call this first — anchor to real clock time
```

## SOP
1. `get_time()` FIRST. Every "in N minutes / at HH:MM / tomorrow" must be
   computed from the real current time, never guessed from chat.
2. Build the cron expression (5 fields: min hour day month weekday):
   - ONE-SHOT ("remind me in 1 minute", "at 22:45 tonight"): current time
     + offset -> specific fields, e.g. 22:46 on Jul 6 -> `46 22 6 7 *`.
   - RECURRING ("every morning at 7:30" -> `30 7 * * *`; "every Friday 5pm"
     -> `0 17 * * 5`). NB `*/5 * * * *` fires ON clock 5-minute marks
     (:00, :05…), NOT five minutes from now — for "in 5 minutes" use a
     one-shot, never `*/N`.
3. Write the prompt as an INSTRUCTION TO FUTURE-YOU, naming the delivery:
   - speak it: `prompt="Say out loud: dinner time!"`
   - message a channel (when a send tool is available): `prompt="Send the
     Discord/Telegram message: standup in 5"`
   - do a task: `prompt="Check the weather and speak a one-line forecast"`
4. Give it a short `name` so it can be cancelled ("dinner", "meds").
5. Confirm to the user WHAT fires WHEN ("set — I'll speak it at 22:46").

## ONE-SHOT CAVEAT (important)
Cron has no native run-once: `46 22 6 7 *` would fire again NEXT YEAR on
Jul 6. For one-shots, END the scheduled prompt with the cleanup order:
`…then call cancel_schedule(name="dinner")`. Future-you does the cleanup.

## ERROR HATCH
- "Did I already set that?" / duplicate names -> `list_schedules()` first.
- Wrong time arithmetic is the #1 failure: re-check against `get_time()`
  output before calling `schedule_prompt`, especially around midnight and
  month ends (Jul 6 23:59 + 2 min = Jul 7 00:01 -> `1 0 7 7 *`).
- Creation is permission-gated (it runs unattended later) — if the user
  denies, drop it; don't retry.

## DONE WHEN
The schedule exists (`list_schedules` shows it with the expected next-run
time), the user was told what fires when, and a one-shot prompt contains
its own `cancel_schedule` cleanup. Never claim a reminder is set without
the `schedule_prompt` call succeeding.
