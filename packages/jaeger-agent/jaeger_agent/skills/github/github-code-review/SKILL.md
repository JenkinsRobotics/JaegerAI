---
name: github-code-review
description: Review an existing GitHub pull request and optionally publish review
  comments. Use when the user provides a PR URL/number or explicitly asks for GitHub
  PR review; use requesting-code-review for local pre-commit review.
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
    - read_file
    - search_files
    tags:
    - github
    - pull-request
    - code-review
    category: github
    related-skills:
    - github-auth
    - github-pr-workflow
    - requesting-code-review
    compatibility: Requires git and authenticated GitHub CLI for remote PR operations.
---

# GITHUB PR REVIEW

## SOP

1. Verify repository and PR identity with `gh pr view`; do not infer from branch
   names alone.
2. Fetch metadata, base/head SHAs, changed files, and the complete diff.
3. Inspect relevant surrounding code and run focused tests without changing code.
4. Record only actionable correctness, security, performance, or maintainability
   findings with file/line evidence; avoid style noise.
5. Read `references/imported-guide.md` only for advanced REST fallback or inline
   review API details.
6. Show the review draft before publishing comments unless the user explicitly
   authorized posting.

## ERROR HATCH

If authentication, repository identity, or diff retrieval fails, stop and report
the exact command failure. Never comment on a guessed PR or SHA.

## DONE WHEN

Findings are prioritized and evidence-backed, tests are reported, and any remote
review publication is confirmed by successful `gh`/API output.
