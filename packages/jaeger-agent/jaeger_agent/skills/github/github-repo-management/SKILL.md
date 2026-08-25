---
name: github-repo-management
description: Create, clone, fork, configure, or release a GitHub repository. Use for
  repository-level GitHub administration; use github-pr-workflow for pull requests
  and github-issues for issue operations.
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
    - repository
    - release
    - remotes
    category: github
    related-skills:
    - github-auth
    - github-pr-workflow
    - github-issues
    compatibility: Requires git; authenticated GitHub CLI is preferred for remote
      mutations.
---

# GITHUB REPOSITORY MANAGEMENT

## SOP

1. Resolve the local path, owner/repository, remote URLs, and authentication.
2. Inspect existing state before any create, remote, visibility, secret, or
   release mutation.
3. Show the exact externally visible change and obtain required confirmation.
4. Prefer `gh`; use documented `git`/REST fallback only when `gh` is unavailable.
5. Read `references/imported-guide.md` only for the selected operation.
6. Re-query GitHub or git state to verify the mutation.

## ERROR HATCH

- Ambiguous owner, repository, remote, visibility, tag, or release target: stop
  and ask rather than guessing.
- Authentication failure: load `github-auth`; do not place tokens in commands.

## DONE WHEN

The exact requested repository operation is verified locally and remotely, with
the resulting URL/name/tag reported.
