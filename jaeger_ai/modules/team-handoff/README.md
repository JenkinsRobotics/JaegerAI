# team-handoff

Job: hand bounded tasks to standing specialists, in parallel, through the Gateway, with approval, in the right project.

Source: the local JaegerAI copy of jaeger-agent, backed up on Desktop at JaegerAI-jaeger-agent-local-2026-10-22/jaeger_agent/tools/call_agent.py (14,592 bytes, vs 8,013 in clean standalone). Do NOT edit packages/jaeger-agent to change this again.

Contents: call_agent.py — call_agent + run_team (parallel specialist fan-out), Gateway base supplied by the host (not hardcoded), 300s approval wait, native agent registry lookup.

How it bolts on (not yet wired, not yet tested): register call_agent and run_team as JaegerAI tools via the tool registry; Gateway base and auth supplied by the host seam. Clean jaeger-agent's own call_agent.py (8,013 bytes) stays in packages/jaeger-agent and is not overwritten by this module.

Test to run when code-run is available: call a specialist, require approval, check the result is persisted, check run_team returns all specialists, check a denied handoff is reported as denied, not as success.
