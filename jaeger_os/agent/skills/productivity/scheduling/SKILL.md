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
schedule_prompt(prompt="Say: dinner time!", in_minutes=5, name="dinner")   one-shot, relative
schedule_prompt(prompt="Say: wake up", at="2026-07-07T07:00", name="wake") one-shot, absolute
schedule_prompt(prompt="…", cron_expr="30 7 * * *", name="meds")           recurring
list_schedules()                       every active schedule + its next-run time
cancel_schedule(name="meds")           remove one by name
get_time()                             call before absolute times — anchor to the real clock
```

## ONE-SHOT vs RECURRING — the #1 mistake
"Remind me IN 5 minutes" fires ONCE -> `in_minutes=5`. "EVERY 5 minutes"
repeats -> `cron_expr="*/5 * * * *"`. Duration ≠ frequency: if the user
said "in", "at", "tonight", or "tomorrow", it is ONE-SHOT — never a cron.
One-shots complete themselves after firing; no cleanup needed.

## SOP
1. Classify: one-shot ("in N minutes / at HH:MM / tomorrow") or recurring
   ("every …"). When unsure, one-shot.
2. One-shot relative -> `in_minutes=N` directly (no time lookup needed).
   One-shot absolute ("at 22:45", "tomorrow 7am") -> `get_time()` first,
   then `at="<ISO local datetime>"`. Recurring -> `get_time()` first, then
   a 5-field `cron_expr` ("30 7 * * *" = 7:30 daily, "0 17 * * 5" =
   Friday 5pm).
3. Write the prompt as an INSTRUCTION TO FUTURE-YOU, naming the delivery:
   - speak it: `prompt="Say out loud: dinner time!"`
   - message a channel (when a send tool is available): `prompt="Send the
     Discord/Telegram message: standup in 5"`
   - do a task: `prompt="Check the weather and speak a one-line forecast"`
4. Give it a short `name` so it can be cancelled ("dinner", "meds").
5. Confirm to the user WHAT fires WHEN, and whether once or repeating
   ("set — I'll speak it once at 22:46").

## ERROR HATCH
- "Did I already set that?" / duplicate names -> `list_schedules()` first.
- User says the reminder keeps repeating -> it was created as a cron by
  mistake: `cancel_schedule(name=…)`, then re-create with `in_minutes`/`at`.
- Creation is permission-gated (it runs unattended later) — if the user
  denies, drop it; don't retry.

## DONE WHEN
The schedule exists (`list_schedules` shows it with the expected next-run
time) and the user was told what fires when — once vs repeating. Never
claim a reminder is set without the `schedule_prompt` call succeeding.
