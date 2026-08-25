---
name: apple-notes
description: Create, search, edit, or export Apple Notes on macOS via the memo CLI.
  Load this for 'put this in Notes', 'find my note about X', 'list my Notes folders'.
  Not for agent-internal memory (use memory) or Obsidian vaults.
metadata:
  jros:
    tags:
    - notes
    - apple
    - macos
    - icloud
    category: desktop
    related_skills:
    - obsidian
    - memory-keeping
    - apple-reminders
    - mac-native
    version: 1.1.0
    platforms:
    - macos
    requires-tools:
    - terminal
---

# APPLE NOTES — memo CLI

Notes.app via `memo`. Syncs over iCloud. Call it through `terminal`,
never raw osascript.

## PREREQUISITES

- macOS + Notes.app
- `brew tap antoniorodr/memo && brew install antoniorodr/memo/memo`
- Automation access for Notes.app when prompted

## TOOLS (exact)

```
terminal(command="memo notes")
terminal(command="memo notes -s \"query\"")
terminal(command="memo notes -f \"Folder Name\"")
terminal(command="memo notes -a \"Title\"")
terminal(command="memo notes --json")
```

## SOP

1. If `memo` is missing → `terminal(command="which memo")`. Not found:
   tell the user the brew install line. Do not invent notes.
2. Search/list with `-s` / `-f` before creating a duplicate.
3. Create with `memo notes -a "Title"` after confirming the title.
   Interactive `-a` / `-e` / `-d` needs a real TTY — prefer flagged
   non-interactive forms from this skill.
4. Agent-only scratch → `memory(action="remember", ...)`, not Notes.
   Markdown vault → `obsidian`.

## ERROR HATCH

- `memo: command not found` → brew install; stop.
- Automation denied → System Settings → Privacy → Automation; stop.
- Note has images/attachments → memo cannot edit it; say so.

## DONE WHEN

A real `memo` command returned the list, the search hit, or the create
result. Never fabricate a Notes.app note.
