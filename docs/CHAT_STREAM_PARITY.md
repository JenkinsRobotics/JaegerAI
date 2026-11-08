# Chat stream consolidation

Scope: stream presentation only. No navigation, avatar, runtime, policy or
recovery redesign. Existing persisted data is not rewritten.

## First pass: shared activity grouping

The existing custom IDE panel is the behavioral baseline. Its timeline module
now owns partitionTurn, consumed by the browser/Mac renderer and IDE work-row
projection. Structured tool/progress/checkpoint boundaries move preceding answer
segments into activity. Reasoning, plans and tools belong there too. No phrase
matching or content-based guesses are used by this partition.

Browser chat shows one initially collapsed Activity disclosure per turn, with
the final answer outside it. The disclosure is accessible during streaming,
keeps work in order, and collapses on completion. This intentionally differs from
the IDE panel's auto-open-on-start behavior to keep the browser transcript quiet.
Warnings, errors, approvals, questions and handoff markers remain outside it.
Tools still retain their detailed outcome states. Reloaded rich parts use the
same grouping function as live parts. Legacy text-only history cannot recover
missing work boundaries; it is left visible instead of guessed.

## Preserve / review inventory

| Capability | First pass | Later decision |
| --- | --- | --- |
| Attachments, drafts, queue/steering, send/stop | Unchanged | Keep |
| Approvals and clarification forms | Outside Activity, unchanged | Keep |
| Handoffs and context receipts | Outside Activity, unchanged | Keep |
| Reactions and message actions | Unchanged | Keep |
| Tool outcomes and summaries | Inside Activity; no parts dropped | Keep |
| Reasoning and intermediate commentary | Inside Activity | Keep grouping |
| Text reveal presets, fade/blur, caret | Unchanged for answers | Review individually |
| IDE plans/checkpoints/sources | Existing IDE handling unchanged | Browser parity pending |
| Native VS Code chat | Unchanged | Separate host adapter still required |

This is not a claim of one fully unified transport or event reducer. SSE
observation, saved-history adapters and native VS Code ChatResponseStream still
have separate host constraints. The shared partition is the first tested seam.
No feature is marked removed in this pass.
