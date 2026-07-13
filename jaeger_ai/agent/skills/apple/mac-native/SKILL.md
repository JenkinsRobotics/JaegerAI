---
name: mac-native
tier: native
requires_tools: [run_shortcut, list_shortcuts, spotlight_search, get_events, create_event,
                 lookup_contact, clipboard_read, clipboard_write, notify, system_control,
                 media_control, now_playing, ocr_file, open_on_host, computer_do, move_file,
                 copy_file, send_email, send_message]
requires_toolsets: [shortcuts, spotlight, calendar, contacts, clipboard, notifications,
                    system_control, media_control, ocr, files, computer_use]
description: "The 0.9.3 mac-native tool suite: Shortcuts, Spotlight search, Calendar/Contacts, clipboard, notifications, system control (volume/brightness/dark mode/DND/prevent-sleep), media control, and OCR. Load this for ANY 'find my X' / 'run my Y shortcut' / 'what's on my calendar' / 'copy that' / 'turn on dark mode' / 'read the text in this' ask — it hands you the exact tool + the decision rule for when to reach for it instead of Shortcuts/AppleScript/the screenshot loop."
version: 1.0.0
platforms: [macos]
metadata:
  jros:
    tags: [shortcuts, spotlight, calendar, contacts, clipboard, notifications, system-control,
           media-control, ocr, macos, native-first]
    category: desktop
    related_skills: [macos-computer-use, file-organization, email-triage]
---

# MAC-NATIVE TOOL SUITE

Nine small, specific tools over macOS system services — Shortcuts, Spotlight,
Calendar/Contacts, clipboard, notifications, system control, media control,
and OCR. Each one is a single, near-instant round-trip (an `osascript` call,
an `mdfind` query, a CLI invocation) — never the screenshot/click loop.

## WHICH LADDER: shortcuts vs AppleScript vs computer_do vs this suite

Four ways to make something happen on this Mac. Pick the cheapest one that
covers the ask — same cost-ordering discipline as `macos-computer-use`'s
rung system:

1. **A dedicated tool in THIS skill** — the ask maps directly onto one of
   the nine verbs below (find a file, read the calendar, control volume,
   OCR an image, ...). Cheapest, most reliable, always try first.
2. **`run_shortcut`** — the user has (or wants) a Shortcuts.app automation
   that does something none of the dedicated tools cover, OR the ask names
   a shortcut by name ("run my Morning Routine shortcut"). A shortcut can
   do ANYTHING its author built — treat it as opaque, not a peer of the
   scoped tools above.
3. **`open_on_host` / `computer_do`** (see `macos-computer-use`) — driving
   an app's UI directly: opening a URL/app, clicking something, changing a
   setting THIS skill doesn't cover.
4. **The screenshot/click loop (`computer_use_v1`)** — LAST RESORT, only
   when 1-3 genuinely can't reach the target.

Don't reach for a Shortcuts automation OR the screenshot loop to do
something a single call here already does (e.g. "turn on dark mode" is
`system_control(action="dark_mode", value="on")`, never a shortcut or a
click through System Settings).

## THE NINE TOOLS

```
list_shortcuts()                              what's installed
run_shortcut(name, input=None)                 run one (tier-2, confirms every call)

spotlight_search(query, kind=None, since=None, limit=20)
                                                find files anywhere by metadata
                                                kind: screenshot/image/pdf/document/app
                                                since: today/yesterday/week/month/"<N>"

get_events(day=None, start=None, end=None)     read the calendar
create_event(title, start, end, notes=None)    add an event (tier-2)
lookup_contact(name)                           resolve a person -> emails/phones

clipboard_read()                               what's on the clipboard
clipboard_write(text)                          put something on it (tier-1)

notify(title, message)                         on-screen banner (tier-1)

system_control(action, value=None)             volume/brightness/dark_mode/
                                                do_not_disturb/prevent_sleep (tier-2)

media_control(action)                          play/pause/next/skip/previous (tier-2)
now_playing()                                  what's playing right now (read-only)

ocr_file(path)                                 extract text from an image/PDF
```

## SPOTLIGHT-FIRST FILE FINDING

`spotlight_search` is the FIRST move for "find my X" / "where's the Y from
last week" — it searches the whole indexed disk by real metadata (kind,
dates, screenshot flag), not a directory walk. It pairs directly with
`move_file`/`copy_file`: find the path, then act on it.

```
spotlight_search(kind="screenshot", since="week")
  -> results: [{path: "/Users/x/Desktop/Screenshot ....png", ...}, ...]
move_file(src="<that path>", dst="workspace/Screenshots/...")
```

Reach for `search_files` instead only when the target is confined to the
sandboxed skills/ workspace and you need to grep file CONTENTS, not find a
file by name/kind/date across the whole disk.

## CALENDAR + CONTACTS RECIPES

- "what's on my calendar {today/tomorrow/Thursday}" ->
  `get_events(day="today")` (or an ISO date).
- "add {X} to my calendar {when}" -> `create_event(title=..., start=...,
  end=..., notes=...)`. Confirm the time back to the user if it was
  ambiguous ("Thursday" with no year assumes the nearest upcoming one).
- ANY time the user names a PERSON rather than giving you a raw address/ID
  ("email Sam the deck", "message Sam", "invite Sam") -> `lookup_contact
  (name="Sam")` FIRST, then feed the resolved email/phone into
  `send_email`/`send_message`. Never guess an address. If lookup_contact
  finds more than one match, ask which one rather than picking.

## SYSTEM / MEDIA / CLIPBOARD ONE-LINERS

```
"turn on dark mode"              -> system_control(action="dark_mode", value="on")
"turn the volume down to 20"     -> system_control(action="volume", value=20)
"don't let my Mac sleep for 30min" -> system_control(action="prevent_sleep", value=30)
"pause the music" / "skip this"  -> media_control(action="pause") / media_control(action="skip")
"what song is this"              -> now_playing()  (read-only, no confirmation)
"copy this for me" / "what did I copy" -> clipboard_write(text=...) / clipboard_read()
"notify me when X" (on-screen, not a message to someone) -> notify(title=..., message=...)
```

## THE COMPOUND EXAMPLE

"Find last week's deck, add Thursday review, email it to Sam":

```
1. spotlight_search(kind="document", since="week", query="deck")
   -> pick the matching path from results
2. create_event(title="Review", start="<Thursday 2pm ISO>", end="<+1h ISO>")
3. lookup_contact(name="Sam")
   -> resolve Sam's email from matches
4. send_email(to="<resolved email>", subject="Deck for review",
              body="Here's the deck ahead of Thursday's review.",
              cc=None)
```
Four tools, four calls, no shortcut authored, no screenshot taken. Show the
draft before step 4 per `email-triage`'s rule (a short, user-dictated
message is pre-approved; anything you composed needs a look first).

## ERROR HATCH

- `run_shortcut` reports "no shortcut named X" -> call `list_shortcuts()`
  and re-check the name; don't retry the same guess.
- `spotlight_search` returns 0 results -> loosen `kind`/`since` before
  concluding the file doesn't exist; Spotlight indexing can lag a just-
  created file by a few seconds.
- `create_event`/`get_events` report a date-parse error -> your `day`/
  `start`/`end` didn't parse; use an ISO date/datetime string
  ("2026-07-16T14:00") rather than a loose phrase.
- `lookup_contact` returns `found: False` -> say so plainly; never invent
  an address to unblock a send.
- `system_control(action="brightness", ...)` reports the `brightness` CLI
  is missing -> relay the `brew install brightness` fix; don't fall back
  to the screenshot loop to drag a slider.
- `system_control(action="do_not_disturb", ...)` succeeds but the note
  flags Sonoma+ Focus modes -> tell the user it may not have taken, and
  that a Shortcuts automation (`run_shortcut`) is the more reliable path
  on newer macOS.
- `ocr_file` returns `available: False` -> PyObjC's Vision bridge isn't
  installed; relay the `pip install` command from `error` — never claim
  you read text you didn't.

## EVAL EXAMPLES

| User ask | Expected behavior |
|---|---|
| "find the screenshot I took this morning" | `spotlight_search(kind="screenshot", since="today")` |
| "run my backup shortcut" | `list_shortcuts()` if unsure of the exact name, then `run_shortcut(name=...)` (confirms) |
| "what's on my calendar today" | `get_events(day="today")`, plain summary |
| "what's on my clipboard" | `clipboard_read()` |
| "email Sam the deck" | `lookup_contact(name="Sam")` -> `send_email(to=<resolved>, ...)` |
| "turn on dark mode" | `system_control(action="dark_mode", value="on")` — no shortcut, no screenshot loop |

## DONE WHEN

The user gets a real result sourced from an actual tool call — a genuine
Spotlight hit, a real calendar read, a real clipboard value, a real
contact match — never a fabricated answer standing in for one. For any
tier-2 action (`run_shortcut`, `create_event`, `system_control`,
`media_control` transport actions), the tool actually returned success
before you claim it happened.
