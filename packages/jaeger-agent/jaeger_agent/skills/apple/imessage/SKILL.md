---
name: imessage
description: Send or read iMessage/SMS on this Mac via the imsg CLI. Load this for
  'text Mom I'll be late', 'what did I last message X'. Telegram/Discord/Slack use
  send_message; email uses send_email.
metadata:
  jros:
    tags:
    - imessage
    - sms
    - messages
    - macos
    - apple
    category: desktop
    related_skills:
    - mac-native
    - email-triage
    - messaging-setup
    version: 1.1.0
    platforms:
    - macos
    requires-tools:
    - terminal
    - lookup_contact
---

# iMESSAGE — imsg CLI

Messages.app via `imsg`. Always confirm recipient + exact text before
send. Resolve people with `lookup_contact` first — never guess a number.

## PREREQUISITES

- Messages.app signed in
- `brew install steipete/tap/imsg`
- Full Disk Access + Automation for Messages

## TOOLS (exact)

```
lookup_contact(name="Mom")
terminal(command="imsg chats --limit 10 --json")
terminal(command="imsg history --chat-id 1 --limit 20 --json")
terminal(command="imsg send --to \"+14155551212\" --text \"I'll be late\"")
```

## SOP

1. Named person → `lookup_contact(name=...)`. Multiple matches → ask
   which. `found: False` → say so; do not invent a number.
2. Optional: `imsg chats --limit 20 --json` to confirm the thread.
3. Show the user: to, service (iMessage/SMS), exact body. Wait for
   go-ahead unless they dictated a short literal ("text X I'll be late").
4. `imsg send --to "..." --text "..."`. Report only from the command
   result.

## ERROR HATCH

- `imsg: command not found` → brew install; stop.
- Permission / not authorized → Full Disk Access + Automation; stop.
- Send failed → do not retry (duplicates the text). Show the error.
- Telegram/Discord/Slack → `send_message`, not imsg.

## DONE WHEN

A real `imsg send` succeeded, or a real history/chats list was returned.
Never claim a text sent without the CLI saying so.
