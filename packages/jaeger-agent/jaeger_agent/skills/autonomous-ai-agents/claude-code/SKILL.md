---
name: claude-code
description: "Delegate a bounded coding task to the Claude Code CLI. Use only when the user explicitly requests Claude Code or chooses it over Jaeger's native coding workflow."
license: MIT
compatibility: Requires the `claude` CLI and configured Anthropic authentication.
metadata:
  jros:
    version: 3.0.0
    lifecycle: optional
    skill-class: first-class
    platforms: [linux, macos, windows]
    requires-tools: [terminal]
    tags: [coding-agent, delegation, claude-code]
    category: autonomous-ai-agents
    related-skills: [codex, hermes-agent, opencode]
---

# CLAUDE CODE DELEGATION

This is a provider-specific delegate, not the default coding path.

## TOOL

```text
terminal(command="claude --version")
terminal(command="claude -p '<bounded task>'", timeout=...)
```

## SOP

1. Verify `claude --version` and authentication without exposing credentials.
2. State the exact repository, task, allowed changes, and verification command.
3. Choose print mode for bounded work; use an interactive PTY only when the task
   genuinely needs follow-up interaction.
4. Read `references/imported-guide.md` only for session resume, PTY dialogs, or
   advanced CLI flags.
5. Inspect the resulting diff and test output yourself before reporting success.

## ERROR HATCH

- CLI/auth missing: give the setup requirement and stop.
- The delegate stalls or requests broader permission: stop and return control to
  the user; do not enable bypass flags implicitly.

## DONE WHEN

The delegate completed the bounded task, Jaeger inspected its diff, and relevant
verification passed—or the exact blocker is reported.
