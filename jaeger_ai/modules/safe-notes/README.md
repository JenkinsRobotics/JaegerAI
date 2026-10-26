# safe-notes

Job: a specialist's own memory file, locked and versioned, not cross-readable.

Source: local JaegerAI copy, backed up on Desktop at JaegerAI-jaeger-agent-local-2026-10-22/jaeger_agent/tools/agent_notes.py (7,243 bytes, vs 2,267 in clean standalone). Do NOT edit packages/jaeger-agent to change this again.

Contents: agent_notes.py — locked writer, sha256 version history in .versions/, restore and forget only with the reviewed revision, symlink and read-only protections, read size limits, prompt truncation.

How it bolts on (not yet wired, not yet tested): register agent_notes via the tool registry; Gateway binds the notes dir for the specialist turn, as before. Clean jaeger-agent's simple agent_notes.py stays in packages/jaeger-agent.

Test to run when code-run is available: append, replace, restore an old version, forget with the wrong revision (must refuse), read from another specialist (must refuse).
