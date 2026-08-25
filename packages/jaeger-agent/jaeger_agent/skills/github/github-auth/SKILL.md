---
name: github-auth
description: "Configure or diagnose GitHub authentication with gh, HTTPS credentials, or SSH keys. Use when GitHub commands fail authentication or the user asks to connect an account."
license: MIT
metadata:
  jros:
    version: 2.0.0
    lifecycle: core
    skill-class: first-class
    platforms: [linux, macos, windows]
    requires-tools: [terminal]
    tags: [github, authentication, gh, ssh]
    category: github
---

# GITHUB AUTHENTICATION

## SOP

1. Run `gh auth status` and inspect git remote protocol without printing secrets.
2. Choose one path: `gh auth login`, existing credential helper, or SSH.
3. Prefer interactive `gh auth login`; the user completes browser/device prompts.
4. Never scrape token, credential, or private-key files into agent context.
5. Read `references/legacy-guide.md` only for enterprise hosts, protocol switching,
   or narrowly scoped troubleshooting.
6. Verify with `gh api user --jq .login` and a read-only remote operation.

## ERROR HATCH

Wrong account/host, missing scopes, SSO requirement, or SSH permission failure:
stop and report the exact status. Do not create or replace credentials silently.

## DONE WHEN

The intended GitHub host/account is authenticated and a read-only API/repository
operation succeeds without exposing credentials.
