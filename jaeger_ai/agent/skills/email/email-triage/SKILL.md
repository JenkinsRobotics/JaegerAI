---
name: email-triage
description: "Check, summarize, draft, or send email — 'check my email', 'any new messages', 'draft a reply to X', 'send an email to Y saying Z', 'email John about the meeting'. Load this for ANY email task; it hands you the exact read (himalaya) and send (send_email) paths and the draft-before-send rule."
version: 1.0.0
platforms: [macos, linux, windows]
requires_tools: [send_email]
requires_toolsets: [email]
metadata:
  jros:
    tags: [email, triage, inbox, drafting, himalaya, send_email]
    category: email
    related_skills: [himalaya, web-research]
---

# EMAIL TRIAGE — CHECK / SUMMARIZE / DRAFT / SEND

Two separate surfaces, one rule that bridges them:

- **Reading/checking** the inbox uses the `himalaya` CLI skill (via
  `terminal`) where it's installed — `himalaya envelope list`, `himalaya
  message read <id>`. NOT every station has himalaya configured; if it
  isn't, say so plainly rather than pretending you checked.
- **Sending** uses the dedicated `send_email(to, subject, body, cc=None)`
  tool — Mail.app (AppleScript) first, himalaya CLI as its own fallback
  backend, automatically. Tier-2 (external effect): every send goes
  through the confirmation flow.

## THE RULE THAT MATTERS MOST

**NEVER call `send_email` without the user having seen the exact draft
first** — recipient, subject, and full body, verbatim, in your response —
UNLESS they explicitly said "just send it" / gave you the literal text to
send with no review step implied. "Send an email to X saying Y" where Y
is a short literal message ("saying I'll be 10 minutes late") IS
effectively pre-approved content — send it. "Draft an email to X about Y"
or anything requiring you to compose/expand the message is NOT
pre-approved — show the draft, get a go-ahead (or rely on the tier-2
confirmation prompt itself as the go-ahead gate), THEN send. When in
doubt, show the draft first; a re-prompt costs nothing, an unwanted send
can't be recalled.

## THE TOOLS (exact)

```
terminal(command="himalaya envelope list --page-size 20")        recent inbox
terminal(command="himalaya envelope list from john subject foo") filtered search
terminal(command="himalaya message read 42")                     read one message
send_email(to="a@b.com", subject="...", body="...", cc=None)     send (tier-2)
```
(Full himalaya command reference: `use_skill(name="himalaya")`.)

## SOP

### Checking / summarizing
1. `terminal(command="himalaya --version")` once per session if unsure
   himalaya is set up — a non-zero/command-not-found result means: tell
   the user email reading isn't configured on this station (himalaya
   missing or unconfigured), don't fabricate an inbox summary.
2. `terminal(command="himalaya envelope list ...")` — filter with
   `from`/`subject`/`--folder` when the user named a sender/topic/folder.
3. For a full message, `himalaya message read <id>` before summarizing
   its body — never summarize from the envelope list alone (it has no body).
4. Summarize plainly: sender, subject, one-line gist per message. Flag
   anything that reads as urgent/actionable.

### Drafting / sending
1. Compose the `to` / `subject` / `body` (and `cc` if asked).
2. Show the user the exact draft (unless it's a short literal message
   they dictated verbatim — see the rule above).
3. `send_email(to=..., subject=..., body=..., cc=...)`. This is tier-2 —
   the confirmation prompt is the user's real go-ahead even when you
   showed the draft; don't skip showing it and lean on the prompt alone
   for anything you composed yourself.
4. Report the result plainly from what the tool returned
   (`{sent, backend, ...}` or `{sent: False, error}`) — never claim it
   sent without `sent: True`.

## ERROR HATCH

- `send_email` returns `sent: False` with a Mail.app account error ->
  relay the actionable fix it gives (add a Mail account, or install
  himalaya) — don't retry blindly, the failure mode won't change.
- `himalaya` commands fail / not found -> tell the user reading isn't
  available here; `use_skill(name="himalaya")` has the install/configure
  steps if they want to set it up.
- User asks "did that send?" -> re-check the last tool result, don't
  re-send to verify (a second send duplicates the email).

## EVAL EXAMPLES

| User ask | Expected behavior |
|---|---|
| "check my email" | himalaya envelope list via terminal, plain summary |
| "send an email to jon@x.com saying I'm running late" | draft shown or treated as pre-approved literal text -> send_email fires |
| "draft an email to the team about the outage" | draft shown FIRST, no send_email call until go-ahead |
| "is my email set up" | himalaya --version / config check, grounded answer, no fabrication |

## DONE WHEN

For reads: the user has an accurate summary sourced from a real
`himalaya` call (or a plain "not configured here" if it isn't available)
— never a fabricated inbox. For sends: `send_email` returned `sent:
True` AND the user saw the draft before it went out (or explicitly
supplied the literal text) — never claim a send that didn't return
`sent: True`.
