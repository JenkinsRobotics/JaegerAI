# tool-executor-hardening

Job: make tool execution survive bad model arguments, stay attributed to the right caller, ask the owner when policy requires it, and run authoritative actions once.

Source: local JaegerAI copy, backed up on Desktop at JaegerAI-jaeger-agent-local-2026-10-22/jaeger_agent/tool_executor.py (25,284 bytes, vs 23,395 in clean standalone). Do NOT edit packages/jaeger-agent to change this again, and do NOT replace clean jaeger-agent's tool_executor.py with this file.

Contents: tool_executor.py — Hermes-style argument coercion and validation recovery, caller identity, goal confinement via host registration, owner approval via confirmation provider, authoritative side effects through the once-only ledger.

How it bolts on (not yet wired, not yet tested): use the host seams clean jaeger-agent already provides (caller_identity, register_goal_confinement, confirmation provider) and register this executor as the host's executor wrapper. This file is preserved here as the reference implementation to adapt into that wrapper, not as a drop-in core replacement — adapting it without breaking imports needs a code-level check and a test run.

Test to run when code-run is available: bad tool arguments (must not crash the loop), a delegated worker call (must keep caller identity), a policy-required tool (must ask the owner), a crashed authoritative action retried (must not re-send).
