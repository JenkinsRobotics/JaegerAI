---
name: github-issues
description: Create, inspect, triage, label, assign, comment on, or close GitHub issues.
  Use for issue-tracker operations on a known repository; use github-pr-workflow for
  pull requests.
license: MIT
metadata:
  jros:
    version: 2.0.0
    lifecycle: core
    skill-class: first-class
    platforms:
    - linux
    - macos
    - windows
    requires-tools:
    - terminal
    tags:
    - github
    - issues
    - triage
    - labels
    category: github
    related-skills:
    - github-auth
    - github-pr-workflow
    compatibility: Requires authenticated GitHub CLI for remote mutations.
---

# GITHUB ISSUES

## SOP

1. Resolve owner/repository and inspect existing issue, label, assignee, and
   milestone state before mutation.
2. Search for duplicates before creating a new issue.
3. Draft exact externally visible title/body/comment and requested metadata.
4. Obtain confirmation immediately before create, comment, close, reopen, label,
   assign, transfer, or delete operations unless explicitly pre-authorized.
5. Prefer `gh issue`; read `references/imported-guide.md` only for advanced search,
   REST fallback, templates, or project integration.
6. Re-query the resulting issue and verify number, URL, state, and metadata.

## ERROR HATCH

Ambiguous repository/issue, missing label/assignee, authentication failure, or
possible duplicate: stop and present the choices. Never mutate a guessed target.

## DONE WHEN

The requested issue state is verified on GitHub and its number/URL plus material
metadata are reported.
