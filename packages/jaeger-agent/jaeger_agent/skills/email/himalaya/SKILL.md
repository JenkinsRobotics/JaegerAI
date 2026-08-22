---
name: himalaya
description: "Read, search, send, and manage email from the terminal via the Himalaya CLI (IMAP/SMTP). Load this when the user wants to check, reply to, compose, forward, move, or flag email without a GUI mail client."
version: 1.2.0
platforms: [macos, linux, windows]
requires_tools: [terminal, read_file, write_file]
metadata:
  jros:
    tags: [email, imap, smtp, cli, communication]
    category: email
    related_skills: [hermes-agent]
---

# HIMALAYA EMAIL CLI

Himalaya is a CLI email client (IMAP/SMTP/Notmuch/Sendmail). Every operation is a
shell command — you run it through the JROS `terminal` tool. This skill is the
command cheat sheet; heavy detail is lazy-loaded from `references/`.

## TOOLS (call these)

- `terminal(command="himalaya ...")` — run every himalaya command. Add
  `pty=true` for interactive wizards (e.g. `himalaya account configure`).
- `read_file` / `write_file` — inspect or create `~/.config/himalaya/config.toml`.
- Piping (`cat << 'EOF' | himalaya template send`) is the reliable, non-interactive
  way to compose/reply/forward — prefer it over `$EDITOR` modes.

## REFERENCES (read_file when needed)

- `read_file("references/configuration.md")` — full config, IMAP/SMTP auth,
  Gmail folder mapping.
- `read_file("references/message-composition.md")` — MML syntax for attachments
  and rich bodies.

## PREREQUISITES

1. `terminal(command="himalaya --version")` to verify install. If missing:
   `brew install himalaya` (macOS), the pimalaya `install.sh`, or
   `cargo install himalaya --locked`.
2. A config at `~/.config/himalaya/config.toml` with IMAP+SMTP credentials.
   Fast path: `terminal(command="himalaya account configure", pty=true)`.

## CONFIG GOTCHA (read before first send)

Folder aliases MUST use the plural dotted form directly under the account, e.g.
`folder.aliases.sent = "Sent"`. The pre-v1.2.0 `[accounts.NAME.folder.alias]`
sub-section (singular) parses but is silently ignored — on Gmail this makes
save-to-Sent fail AFTER SMTP delivers, `himalaya message send` exits non-zero, and
a naive retry re-sends the whole email (duplicate to the recipient). Gmail's
`[Gmail]/Sent Mail` mapping is in `references/configuration.md`.

## COMMON OPERATIONS (all via `terminal`)

Read/search:
```bash
himalaya folder list
himalaya envelope list                                  # INBOX
himalaya envelope list --folder "Sent" --page-size 20
himalaya envelope list from john@example.com subject meeting
himalaya message read 42
himalaya message export 42 --full                       # raw MIME
```

Compose / reply / forward (non-interactive — pipe stdin):
```bash
cat << 'EOF' | himalaya template send
From: you@example.com
To: recipient@example.com
Subject: Test Message

Hello from Himalaya!
EOF

himalaya template reply 42   | ... | himalaya template send   # reply
himalaya template forward 42 | ... | himalaya template send   # forward
```

Organize:
```bash
himalaya message move 42 "Archive"
himalaya message copy 42 "Important"
himalaya message delete 42
himalaya flag add 42 --flag seen
himalaya attachment download 42 --dir ~/Downloads
```

Accounts & output:
```bash
himalaya account list
himalaya --account work envelope list
himalaya envelope list --output json     # structured, easy to parse
```

## STATE OFFLOADING

For a triage/reply run over several messages, capture the envelope list with
`--output json` and `write_file` the IDs + decisions before acting, so you don't
lose track across steps.

## ERROR HATCH

- `send` exits non-zero but recipients got it → almost always the folder-alias
  bug above. Fix aliases in the config, then re-run; do NOT blindly retry
  `send` (it re-delivers). Message IDs are per-folder — re-list after moving.
- If a command fails twice, re-run it once with `RUST_LOG=debug` prefixed to
  read the real error, e.g. `terminal(command="RUST_LOG=debug himalaya envelope list")`.

## DONE WHEN

The requested email action (read/searched/sent/moved/flagged) is confirmed —
for sends, a clean exit with the message saved to the Sent folder.
