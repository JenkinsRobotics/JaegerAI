# JaegerAI rebuild — 2026-10-22

What was done, in order, by Matthew's approval on 2026-10-22:

1. Backup: local packages/jaeger-agent copied, as-is, to Desktop/JaegerAI-jaeger-agent-local-2026-10-22/ (verified: 9 top entries, call_agent.py 14,592 bytes, the local version).
2. Restore: packages/jaeger-agent replaced with clean source from standalone /Users/matthewjenkins/GitHub/jaeger-agent (source only — LICENSE, README, pyproject, MANIFEST, VERSION, docs/, jaeger_agent/, scripts/, tests/). Verified: tools/ is now 56 files, call_agent.py is 8,013 bytes (standalone), clarify/mcp tool files are back, build_check.py is gone from packages/jaeger-agent.
3. Modules: 8 independent folders created under jaeger_ai/modules/ from the Desktop backup — team-handoff, safe-notes, verified-messaging, build-check, tool-executor-hardening, workspace-project, effect-ledger, memory-runs. See jaeger_ai/modules/MODULES.md for each module's job, source, and test plan.

What was NOT done:
- Modules are extracted and preserved, NOT yet wired into JaegerAI's runtime, NOT yet tested. No code was run, because the Mac app cannot run code or tests.
- Standalone jaeger-agent repo was NOT edited.
- No other repo was edited. No folders outside jaeger_ai/modules/ were moved in this rebuild.
- No archive was left in the repo. Backups are on the Desktop, per Matthew's preference.

Rule going forward: do NOT modify packages/jaeger-agent to improve it. Improve it with a JaegerAI module, in jaeger_ai/modules/<name>/, bolted on via tool registry, host seam, or Gateway adapter. Edit jaeger-agent in one place only — standalone — or not at all.

Next step, when an agent can run code: wire modules one at a time, test alone then bolted on, starting with build-check, then safe-notes, verified-messaging, team-handoff, then executor / workspace / ledger wrappers. Do not wire all eight at once.
