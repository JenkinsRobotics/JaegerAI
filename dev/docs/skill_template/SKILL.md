---
# Phase-1 unified-architecture frontmatter. Loader currently doesn't parse
# these fields (jaeger.core.skill_loader checks SKILL.md exists but doesn't
# read its contents); they're documented intent until the loader gains
# manifest parsing in a later chunk. See docs/unified_architecture.md §6.1.
name: example
version: 1
kind: human_authored               # human_authored | agent_authored | learned | nn_trained
category: cognitive                # cognitive | physical
runtime: in_process                # in_process | mcp_subprocess
permission_tier: 0                 # READ_ONLY — pure return-a-greeting
embodiment_requires: []            # cognitive skill — runs on any embodiment
authored_at: 2026-05-17
description: Reference skill demonstrating the SKILL.md + module + smoke test contract.
registers_tools:
  - say_example_greeting(name) -> {greeting, skill}
---

# example_v1

## What
The canonical reference skill that ships with Jaeger. Exposes a single tool
`say_example_greeting(name)` that returns a greeting dict. Its only purpose
is to demonstrate the skill contract end-to-end (SKILL.md + module +
smoke test) so humans AND the agent have a working template to copy.

## When
**Never trigger this for real work** — it's a reference, not a production
capability. Copy this folder as a starting point when authoring a new
skill (rename, replace `say_example` with your real logic, update this
SKILL.md, write a real smoke test).

## How
Tool signature: `say_example_greeting(name: str) -> dict`.
Returns: `{"greeting": "Hello, <name>!", "skill": "example_v1"}`.

## Depends on
Nothing. No external libraries, no other skills, no file system access.
