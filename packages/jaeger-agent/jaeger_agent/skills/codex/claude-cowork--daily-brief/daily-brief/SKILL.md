---
name: daily-brief
description: >
  Use this skill when the user asks for a "daily brief", "morning briefing",
  "what's on my plate today", "check my emails", "what do I have today",
  "run my brief", or asks to summarize their emails, calendar, tasks, or reminders
  for the day. Also triggers when the scheduled daily-brief task runs automatically.
version: 0.1.0
---

# Daily Brief Skill

Produce a concise, actionable daily briefing for Matthew by gathering data from all connected sources: Gmail, Apple Mail (including iCloud, Outlook, and Yahoo accounts), Apple Calendar, and Apple Reminders.

## Execution Order

Run these steps in parallel where possible, then synthesize into a single briefing.

### Step 1: Gmail (via Gmail MCP tool)

Use the Gmail search tool to:
- Search `is:unread is:inbox` — retrieve up to 30 unread inbox emails
- Search `is:unread category:spam` — scan spam for miscategorized important emails
- For each unread email, assess priority using the criteria in `references/priority-rules.md`
- Flag any spam emails that appear legitimate for rescue back to inbox (ask user before moving)

### Step 2: Apple Mail (via AppleScript)

Run the AppleScript in `references/applescript-mail.md` to:
- Fetch unread messages from all accounts in Apple Mail (covers iCloud, Outlook, Yahoo if added to Mail.app)
- **Skip any account whose name contains "Gmail" or "Google"** — Gmail is handled via the MCP connector in Step 1 to avoid duplicates
- Return sender, subject, date, and account name for each unread message
- Focus on inbox only; skip Junk folder

### Step 3: Apple Calendar (via AppleScript)

Run the AppleScript in `references/applescript-calendar.md` to:
- Fetch all events for today across all calendars
- Return event title, start time, end time, location, and calendar name

### Step 4: Apple Reminders (via AppleScript)

Run the AppleScript in `references/applescript-reminders.md` to:
- Fetch all incomplete reminders due today or overdue
- Return reminder title, due date, list name, and priority

## Running AppleScript via Bash

Execute AppleScript using:
```bash
osascript -e '<script here>'
```
Or for multi-line scripts, write to a temp file and run:
```bash
osascript /tmp/script.scpt
```

## Output Format

Present the briefing in this order:

1. **📅 Today's Schedule** — list events chronologically with time and title
2. **📧 Priority Emails** — urgent/important emails needing action today, grouped by account
3. **✅ Tasks & Reminders** — overdue items first, then due today
4. **🗑️ Spam Check** — note if any legitimate emails were found in spam (ask before rescuing)

Keep the brief scannable. Use short bullet points. Surface action items clearly.
If a section has nothing to report, skip it or note "Nothing for today."

## Error Handling

- If AppleScript fails (permissions denied), tell the user they may need to grant Automation permissions to the terminal in System Settings → Privacy & Security → Automation.
- If Gmail MCP is unavailable, note it and continue with Apple Mail data.
- Never fail silently — always report which sources succeeded and which didn't.
