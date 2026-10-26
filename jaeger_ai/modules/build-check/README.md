# build-check

Job: run a short list of allowed build/test commands in a project root and return JSON evidence, so a pass is recorded by the host, not taken from the model's word.

Source: JaegerAI-only file, backed up on Desktop at JaegerAI-jaeger-agent-local-2026-10-22/jaeger_agent/tools/build_check.py (5,423 bytes). It was not in clean standalone jaeger-agent at all. Do NOT add it back into packages/jaeger-agent.

Contents: build_check.py — run_build_check, allowed commands npm / node / python3 / pytest / make / swift / git (status/diff/log only) / ls / test, timeout, minimal environment, no shell, expected-files check.

How it bolts on (not yet wired, not yet tested): register run_build_check via the tool registry; Gateway calls this module for POST /v1/projects/{id}/check.

Test to run when code-run is available: a passing test command, a failing command, a disallowed command (must refuse), a missing expected file (must fail).
