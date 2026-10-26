# workspace-project

Job: tools run in the project you switched to, not in a throwaway tempdir, and not in the skills directory.

Source: local JaegerAI copy, backed up on Desktop at JaegerAI-jaeger-agent-local-2026-10-22/jaeger_agent/core/workspace.py (26,456 bytes, vs 24,403 in clean standalone). Do NOT edit packages/jaeger-agent to change this again.

Contents: workspace.py — instance layout binding, workspace override, project_root ContextVar, sandboxed path resolver, audit logger, git auto-commit helper for file_write.

How it bolts on (not yet wired, not yet tested): JaegerAI workspace adapter that binds project_root / layout before tools run, using clean jaeger-agent's workspace seam. Clean jaeger-agent's core/workspace.py stays in packages/jaeger-agent.

Test to run when code-run is available: switch project, run a shell/read/grep tool, check it actually ran in the new project root.
