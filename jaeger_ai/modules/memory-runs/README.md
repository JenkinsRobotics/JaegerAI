# memory-runs

Job: run and memory tracking refinements from the local JaegerAI copy. This module is preserved, not yet proven as a distinct feature — check the diff before wiring it in, and drop it if it shows no distinct feature.

Source: local JaegerAI copy, backed up on Desktop at JaegerAI-jaeger-agent-local-2026-10-22: cognition/sqlite_runs.py (15,568 vs 15,123 standalone, +445), memory/memory.py (53,879 vs 52,752, +1,127), memory/sqlite_store.py (42,919 vs 42,278, +641). Do NOT edit packages/jaeger-agent to change these again.

How it bolts on (not yet wired, not yet tested): JaegerAI memory adapter on top of clean jaeger-agent's SQLite memory, if a real feature is found in the diff. Clean jaeger-agent's memory files stay in packages/jaeger-agent.

Test to run when code-run is available: only after a line diff shows what actually changed in these three files. If no distinct feature is found, delete this module folder and keep clean jaeger-agent memory.
