# entity-runtime — monolith break-out module (split plan, NOT yet cut)

Original file: jaeger_ai/core/entity/runtime.py, 57,253 bytes, largest entity file. Other entity files are already split: verification.py (36,907, 856 lines, single job — do NOT split it, see below), cognition_router.py (22,710), events.py, event_store.py, authority.py, memory.py, deliberate_planner.py, indexing.py, sleep_time.py, executive.py, reflection.py, learning.py, owner_agent.py, self_refine.py, plus sensors/ and skills/ subfolders.

Proposed split:
- entity-turn-prepare — turn preparation, context, cognition routing input.
- entity-turn-execute — turn execution, agent loop invocation.
- entity-turn-finish — turn finish, events, status, persistence.
- entity-status — runtime status reporting.

Do NOT split verification.py in this module. Verification is one job: prove an effect, do not claim it (ATTEMPTED != VERIFIED, verify_disk_state probe). Splitting it risks breaking the approval/verification boundary. Register verification as its own module, leave its code alone.

Overlap with jaeger-agent: entity runtime is JaegerAI's entity layer, jaeger-agent is the brain module it hosts. Do NOT copy jaeger-agent's cognition/world into this module, and do NOT edit jaeger-agent. The seam needs a code-level import check, not a name check, when code-run is available.

Test to run when code-run is available: one full turn through prepare/execute/finish, with verification still separate, after each split group.
