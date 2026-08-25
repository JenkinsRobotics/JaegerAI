---
name: xurl
description: "Read or mutate X/Twitter through the official xurl CLI. Use when the user explicitly asks to search X, inspect timelines, post, reply, DM, upload media, or call an X API v2 endpoint."
license: MIT
compatibility: Requires xurl and user-configured X developer authentication.
metadata:
  jros:
    version: 2.0.0
    lifecycle: plugin
    skill-class: first-class
    platforms: [linux, macos]
    requires-tools: [terminal]
    requires-plugins: [x]
    tags: [x, twitter, social-media, api]
    category: social-media
---

# XURL

Treat reads and writes differently. Posting, replying, deleting, following,
blocking, messaging, and media upload are external mutations.

## SOP

1. Verify `xurl --version` and authenticated identity without printing tokens.
2. For reads, run the narrowest shortcut/API endpoint and parse returned JSON.
3. For writes, draft the exact account/action/content, show it to the user, and
   obtain confirmation immediately before execution.
4. Read `references/imported-guide.md` only for the selected shortcut, endpoint,
   pagination, media upload, or streaming behavior.
5. Execute once and verify the returned object ID/status; never retry a mutation
   merely because display formatting failed.

## ERROR HATCH

Auth/rate-limit/API error: report status and reset time; do not rotate credentials,
switch accounts, or retry writes blindly.

## DONE WHEN

Read results are sourced from returned JSON, or the requested mutation has a
verified object ID/status and exact account.
