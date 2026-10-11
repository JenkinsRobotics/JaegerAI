# JaegerAI 0.14.0 release record

**Classification:** RELEASE RECORD
**Target:** `0.14.0`
**Branch:** `release/0.14.0`
**Tag:** `0.14.0`
**Date:** 2026-10-11

## Included

- One Gateway-owned execution path with durable task ownership, authoritative
  transitions, cancellation, approvals, caller authentication, and session
  continuity across clients.
- Persistent Jaeger and specialist-agent sessions, scoped notes, explicit
  handoffs, archived probe sessions, and durable handoff-summary annotations.
- WebUI companion, local Kokoro speak-first delivery, proactive initiative,
  tailnet notification support, and safer loopback-first remote access.
- IDE conversation parity, caller authentication, existing-worktree selection,
  change review, verification runner, and opt-in Gateway auto-start.
- Owner-granted framework discovery/read/delegation for Claude Code, Codex,
  Gemini, and Grok. Delegated patches are saved as private artifacts and can
  only be applied to the request-bound Git root after fresh owner approval and
  `git apply --check`.
- Gateway turns load shipped code skills before the agent snapshots its tool
  registry. Bare delegate CLI runs bind the active operator instance and retain
  their durable run directory.
- Native vision uses Jaeger's active llama.cpp model and configured projector;
  the former second Moondream model and dependency path are removed.
- Local inference uses a 300-second no-progress timeout while decoded-token
  progress continues to refresh liveness.

## Grok audit disposition

The temporary `shuwalker/jaeger-phase-1b-audit` repository was reviewed
commit-by-commit. Its Phase 1B changes are already represented in this history.
Its later `JaegerBeing` and `core/gateway/one` branches are audit prototypes
that introduce duplicate runtime, event, identity, memory, and task authorities;
they are intentionally not merged. Their useful contracts are enforced here by
the existing Gateway, `GatewayTaskOwner`, `GatewayEventBus`, policy kernel, and
memory subsystem.

## Verification

Release evidence is recorded only after the final release commit passes:

- complete unit tier: **5,804 passed, 11 skipped, 0 failed**;
- canonical `./scripts/verify.sh`: **green** (hygiene 9, IDE 166, core 12);
- wheel/sdist, macOS app, and IDE VSIX inspection: pending;
- installed IDE and live Gateway/client acceptance: pending.

Nothing in this record treats a source edit or a packaged artifact as proof of
installed runtime behavior.
