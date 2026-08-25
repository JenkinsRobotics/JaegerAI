---
name: macos-mail-organizer
description: Organize, triage, deep-clean, search, or filter Apple Mail on macOS. Use for 'deep clean my inbox', 'go through thousands of emails', 'file receipts', 'what's unread', 'set up daily inbox sweep'. Bounded Mail.app tools — never raw osascript / every message.
metadata:
  jros:
    tags: [email, mail, inbox, triage, applescript, macos, sweep, deep-clean]
    category: email
    related_skills: [email-triage, himalaya, mac-native]
    version: 1.2.0
    platforms: [macos]
    requires-tools: [list_mailboxes, list_mail, read_mail, plan_mail_triage, move_mail, batch_move, sweep_mail, schedule_inbox_sweeper, send_email]
    requires-toolsets: [email]
    tier: native
---

# macOS Mail Organizer

Use this skill for ANY Apple Mail organize / triage / deep-clean / search
task.

Do **not** write AppleScript. Do **not** call `execute_code` / `run_python` /
`run_shell` / `terminal` with `osascript`. Unbounded `every message` queries
lock Mail.app for 120s. Tools below are bounded (max 25 headers/ids, 15s
timeout), account-scoped, and resolve nested Gmail mailboxes plus aliases.

Accuracy over speed. Sender address alone never justifies trashing or
auto-filing. Receipts, finance, security/authentication notices, and
anything uncertain stay in the inbox until the user confirms. A body peek
can upgrade a message to keep; it never demotes a keep to trash.

## Tools

```
list_mailboxes()
    accounts + nested mailbox paths. Always step 1 of a new session.

list_mail(account, mailbox="INBOX", limit=10, unread_only=false, offset=0)
    headers only. limit clamped to 25. Deep clean uses offset and
    unread_only=false.

read_mail(account, mailbox="INBOX", message_ids)
    plaintext snippet, 1–5 ids. Verify receipts / uncertain keep-candidates.

plan_mail_triage(account, mailbox="INBOX", offset=0, limit=25, peek=true)
    one page of keep-first proposals. Never moves. Deep-clean primitive.

batch_move(account, source_mailbox, target_mailbox, message_ids)
    many ids, one AppleScript transaction. Inspect success + moved_count.

move_mail(message_id, account, source_mailbox, target_mailbox)
    one id. Prefer batch_move.

sweep_mail(account=None, mailbox="INBOX", limit=25, dry_run=true)
    daily noise only. NOT a deep clean.

schedule_inbox_sweeper(morning_hour=8, evening_hour=18)
    twice-daily sweep_mail(dry_run=false).
```

## Deep clean (thousands of mixed messages)

Trigger: "deep clean", "go through all my email", "thousands", "keep
receipts / important mail".

This is a multi-turn job. One confirmed page per turn. Never
`sweep_mail(dry_run=false)`.

1. `list_mailboxes()` once. Pick the account. Note keep folders
   (`Receipts`, `Finance`, `GitHub-Noise`, `Archive`).
2. `plan_mail_triage(account=..., mailbox="INBOX", offset=0, peek=true)`.
3. Show a table split into:
   - **KEEP for reference** — Receipts, Finance (file to those folders;
     missing folder → `archive`, never trash)
   - **FILE out of inbox** — ordinary GitHub notifications (kept in
     GitHub-Noise); GitHub security/authentication notices stay in Action
   - **TRASH** — high-confidence promo only
   - **LEAVE** — Action / low-confidence. Do not guess.
4. For any KEEP row you still doubt, `read_mail` that id and show the
   snippet before proposing a destination.
5. Confirm with the user. Then `batch_move` per destination. Inspect
   `success` and `moved_count`.
6. **After a successful move, the next page is offset=0** (the inbox
   compacted). `next_offset` is only for a no-move preview scan.
   `after_move_offset` is always 0.
7. Stop the turn after one page. Ask to continue. Repeat until
   `count` is 0.

Empty page with `offset=0` after filing means that account is done —
that is success, not a retry.

## Quick glance (unread only)

`list_mail(..., limit=10, unread_only=true)` → table → confirm →
`batch_move`. Same keep-first buckets.

## Evaluation gate

Every Mail.app tool returns `{ok, success, moved_count, error}`.
- `success` false / `timed_out` / `error` set → halt, tell the user.
  Do not retry. Do not invent AppleScript.
- Two identical failures trip the 2-strike breaker. Stop.

## Anti-loop

- Never `every message`. Never root `mailbox "INBOX"` without an account.
- Never loop `move_mail` when `batch_move` will do.
- Never page with a stale offset after moving — always `offset=0`.
- Timeout or mailbox-resolve error → halt, do not vary folder names.
- Treat a batch as successful only when `success=true` and `moved_count`
  exactly equals the number of requested ids. A partial move is a failure;
  report it and stop rather than guessing which messages moved.

## Done when

The user has a real header/plan sourced from `plan_mail_triage` or
`list_mail`, keep-for-reference mail is in Receipts/Finance/Archive (or
still in INBOX if unconfirmed), and every `batch_move` reported
`success` with a matching `moved_count`. Never a fabricated inbox.
Never trash a receipt or an uncertain message.
