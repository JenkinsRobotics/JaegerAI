---
name: github-pr-workflow
description: Create, update, check, or merge a GitHub pull request. Use for the PR
  lifecycle after code changes exist; use github-code-review for review findings and
  github-repo-management for repository administration.
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
    - write_file
    - patch
    - read_file
    tags:
    - github
    - pull-request
    - branch
    - ci
    - merge
    category: github
    related-skills:
    - github-auth
    - github-code-review
    - github-issues
    compatibility: Requires git and authenticated GitHub CLI for remote operations.
---

# GITHUB PR WORKFLOW

## SOP

1. Inspect repository, current branch, worktree, remotes, and base branch.
2. Verify relevant tests and review the exact diff before committing or pushing.
3. Create a focused branch/commit and draft the PR title/body from verified changes.
4. Show externally visible text and destination before push/PR creation unless the
   user already explicitly authorized that exact action.
5. Use `gh pr create`/`edit`/`checks`; read `references/imported-guide.md` only
   for advanced REST fallback, stacked PR, CI, or merge details.
6. Merge only with explicit authorization and passing required checks.
7. Re-query the PR and report URL, state, checks, and merge result.

## ERROR HATCH

Wrong/dirty branch, ambiguous base, failing tests/checks, or authentication error:
stop and report state. Never force-push, bypass protection, or merge by guessing.

## DONE WHEN

The requested PR operation is visible on the intended repository/base, its URL
and checks are verified, and no unrelated worktree changes were included.
