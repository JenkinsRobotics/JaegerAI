---
name: github-auth
description: "Configure or diagnose GitHub authentication with gh, HTTPS credentials, or SSH keys. Use when GitHub commands fail authentication or the user asks to connect an account."
license: MIT
metadata:
  jros:
    version: 2.1.0
    lifecycle: core
    skill-class: first-class
    platforms: [linux, macos, windows]
    requires-tools: [terminal]
    tags: [github, authentication, gh, ssh]
    category: github
---

# GITHUB AUTHENTICATION

## SOP

1. Run `gh auth status` and inspect the git remote protocol without printing
   secrets. If the intended account is already active, reuse it and skip login.
2. If `gh` is missing, identify the host package manager and install the official
   GitHub CLI through the normal tool approval flow. Verify `gh --version` before
   continuing. Do not ask the user to copy an install command into a terminal.
3. Prefer `gh auth login --hostname github.com --git-protocol https --web` in a
   PTY. Keep the process alive, answer its local prompts, and let it open the
   browser/device flow on the same host. Use the host computer/browser tool when
   the CLI cannot focus the page itself.
4. Enter the one-time device code for the user. When GitHub shows the final OAuth
   grant, summarize the account, application, organization access, and requested
   scopes. Pause at that final grant until the user explicitly approves it. Never
   treat a prior install approval as authorization for account access.
5. Resume the PTY after the browser grant and wait for a success or failure result.
   A page transition alone is not proof that authentication completed.
6. Never run `gh auth token`, print a token, read credential/keychain files, paste
   tokens into chat, or route credentials through model context. Let `gh` store its
   credential in the operating-system keychain.
7. Verify with `gh auth status`, `gh api user --jq .login`, and one read-only
   repository/API operation. Report the connected account and scopes without
   exposing credential values.
8. Read `references/legacy-guide.md` only for enterprise hosts, protocol switching,
   SSH, or narrowly scoped troubleshooting.

## INTERACTION CONTRACT

Treat setup as one visible, resumable operation with these phases:

`inspect -> install_cli -> open_device_flow -> await_oauth_grant -> verify -> ready`

- Surface the active phase in the chat/tool feed; do not hide a blocked login in a
  thought or leave the user with an unexplained spinning command.
- Keep the device-code page and PTY tied to the same operation. If the code expires,
  cancel the old process and start a fresh flow instead of reusing stale state.
- The final OAuth grant is the only account-access checkpoint. Package installation
  and other unsafe local changes still use their own normal tool approvals.
- On success, emit a receipt such as `GitHub connected as <login>` and continue the
  original task. On denial or failure, preserve the original task and report the
  exact recovery step.
- Re-running the workflow is idempotent: a verified active account returns `ready`
  without reinstalling the CLI or starting another OAuth flow.

## ERROR HATCH

Wrong account/host, missing scopes, SSO requirement, or SSH permission failure:
stop and report the exact status. Do not create or replace credentials silently.

## DONE WHEN

The intended GitHub host/account is authenticated, `gh auth status` is healthy,
and a read-only API/repository operation succeeds without exposing credentials.
