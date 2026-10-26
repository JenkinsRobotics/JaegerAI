# main-cli — monolith break-out module (split plan, NOT yet cut)

Original file: jaeger_ai/main.py, 287,440 bytes, 6,303 lines. Jaeger CLI, "intentionally self-contained" per its own docstring: no imports from memory/, messaging/, or other framework dirs, only third-party + sibling modules under jaeger_os/.

Lifecycle in order, from its docstring: instance dir, setup wizard, exclusive lockfile, manifest schema check, tools+memory binding, in-process Gemma model load, PydanticAI agent with v2 system prompt + identity, built-in tools, skill loader (base + instance, smoke-test gating, instance-wins-over-core), chat loop (slash commands + multiline paste).

Why this folder exists: same reason as gateway-server — to make the split easy to edit/modify/test, WITHOUT cutting a 287KB file blind today. Check first whether main.py is still the live CLI entry: its docstring loads an in-process Gemma model, while the confirmed Jaeger definition is cloud LLM today / on-device goal. Do not split it on the assumption it is the live path.

Proposed split, leaving main.py as a thin launcher only:
- cli-lifecycle — instance dir, lockfile, manifest check.
- cli-skill-loader — base + instance skills, smoke-test gating, resolution.
- cli-chat-loop — chat loop, multiline paste detection.
- cli-slash-commands — slash command handlers, by group.
- cli-model-boot — model load + PydanticAI agent build, separated from lifecycle.

Overlap with jaeger-agent: main.py already imports jaeger_agent (tools, memory, prompts, background cron) and jaeger_os — that is normal host usage, not a copy. Do NOT copy jaeger-agent's agent loop into this module, and do NOT edit jaeger-agent to fit the CLI.

Test to run when code-run is available: start CLI, wizard/lock/manifest path, skill loader gating, one chat turn, one slash command, each after its own split group, with the original CLI behavior as the reference.
