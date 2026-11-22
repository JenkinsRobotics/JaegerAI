# Agent runtime assurance

The "big three" reference implementations are Codex, Grok Bot, and Hermes Agent.
Jaeger keeps its existing Gateway, authority kernel, task owner, and context
compiler. The following changes repair those boundaries rather than installing
another agent loop.

## Resource authority

`core/authority/filesystem.py` derives protected data paths from the framework
discovery catalog and owner grants. File helpers check resolved paths, including
files discovered by recursive search. Connector reads retain their own scoped
grant checks, redaction, source framing, and audit trail.

A read grant does not authorize writes to another agent's history or memory.
It also does not grant arbitrary shell, PTY, or background processes ambient
access to those stores. Those processes always exclude the stores; use a bounded
file or connector read with the required grant instead. Thus a detached process
cannot retain store access after a later grant revocation. Shared catalog
subtrees require all relevant read grants for direct file reads; a connector can
still access only its granted collection.

macOS uses Seatbelt path restrictions inherited by child processes. Existing
default-deny Python profiles receive additional denials without widening their
allow rules. Linux accepts the existing isolated Bubblewrap Python launcher only
when its explicit mounts cannot expose protected resources. Arbitrary Linux shell
execution has no equivalent backend here and fails explicitly; it never falls
back to an unconfined process. Linux policy construction is tested on macOS;
Linux kernel enforcement requires a Linux runner.

This is a local filesystem boundary, not complete machine containment. It does
not establish isolation from privileged localhost APIs, remote services, all
credential stores, or pre-existing processes. Framework secret filtering remains
stricter in the connectors than in generic shell execution.

## Context and summaries

Optional recall receives a bounded share of the configured serving window after
the completion reserve. An unknown route does not borrow another model's window.
The cognition formatter honors the admitted allowance rather than silently
clamping it to 4,000 characters. Durable storage and retained model context remain
separate facts, exposed through context provenance.

Summary coverage advances only through complete messages actually supplied to
the summarizer, preserving request/answer boundaries. Recent retained messages
are supplied to reconcile completed or cancelled work. Model-authored summaries,
including existing summaries, enter cognition as historical assistant data and
cannot establish standing instructions or permissions. Summary prose still needs
epistemic discipline; role and coverage checks do not guarantee factual synthesis.

## Evidence and completion

Connector inventories report `contents_read=false`. Reads report byte coverage,
source/content truncation, and extracted/skipped JSONL record counts. Counting
files and reading excerpts are not comprehensive inspection.

Gateway terminal receipts distinguish `status_scope=request_execution` from
outcome verification: `verified`, `not_verified`, or `not_performed`. Worker
self-reports are retained as such and cannot establish independent verification.
Provider-reported model identity travels through the owner execution callbacks;
the configured route is never substituted for an unknown observed identity.

## Reference basis

Patterns were implemented independently; no proprietary code was transplanted.

- Codex: [Seatbelt policy](https://github.com/openai/codex/blob/main/codex-rs/sandboxing/src/seatbelt.rs),
  [filesystem boundary](https://github.com/openai/codex/blob/main/codex-rs/file-system/src/lib.rs),
  [compaction](https://github.com/openai/codex/blob/main/codex-rs/core/src/compact.rs).
  Official upstream source, Apache-2.0; installed CLI `0.156.1` was identified,
  but upstream was not asserted identical to that installed binary.
- Hermes Agent: local clean commit `c7da41dd522dc19cc08bbfcfa69d4b078224b45d`,
  MIT; `agent/context_compressor.py`, `tools/memory_tool_store.py`,
  `agent/verification_evidence.py`. Its file guard explicitly is not an OS
  security boundary; Jaeger does not treat it as one.
- Grok Bot: installed `1.1.0`, `dist/local-exec-daemon/main.cjs` in `app.asar`,
  SHA-256 `2ce3b335f3d92c7be6ad59da397f8f6bf16c6d29474041ec5cc1e508b65b8e48`.
  Static inspection identified typed sandbox policies and explicit
  unsupported/denied outcomes. This is shipped-client evidence, not proof of
  server-side memory or execution behavior. REA record:
  `ev_a817350597e467ea065b312612f4f166c02f827adabdfd3625d1e414be11c9b5`.

`scripts/verify.sh` includes the new authority, history, context, and completion
regressions. Passing that pipeline verifies source behavior in isolation, not a
deployment or a live model's compliance with every reporting instruction.
