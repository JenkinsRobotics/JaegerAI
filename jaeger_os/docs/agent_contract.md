# Agent contract

Auto-generated from `jaeger_os/core/prompts/rules.py` by
`dev_scripts/generate_agent_contract.py`. Do not hand-edit — re-run the
script after changing `rules.py` and the diff will land here.

This document mirrors the **literal text** the agent sees in its
system prompt every turn. Treat it as the canonical contract between
the framework and the model: anything the agent is told to "always",
"never", "MUST", "before X" lives here.

The actual system prompt is the concatenation of these blocks plus
per-instance content (`identity.yaml`, `soul.md`) — see
`core/prompts/assemble.py` for the weave order.

## `JAEGER_OS_CONTEXT`

_(missing in rules.py — generator skipped)_

## `MANDATORY_TOOL_RULES`

_(missing in rules.py — generator skipped)_

## `OPERATING_DISCIPLINE`

_(missing in rules.py — generator skipped)_

## `TOOL_USAGE_RULES`

_(missing in rules.py — generator skipped)_

## `RUNTIME_TAIL_BASE`

_(missing in rules.py — generator skipped)_

## `RUNTIME_TOOLSET_SCOPED`

_Tail block appended when ``JAEGER_TOOLSET_SCOPING`` is ON (``load_toolset`` widens the active surface)._

```text
- You see a focused CORE set of tools. The categories below list every
  OTHER tool that's installed but not currently in your active set.
  Two ways to reach them:
    • `describe_tool("name")` — peek at one tool's exact schema
      without loading anything. Cheap. Use this when you just need to
      know "can I call X?" or "what args does X take?"
    • `load_toolset("category")` — add a whole category to your
      active set for the rest of the session. Use this when you'll
      need several tools from the same area.
  Tools you don't see do NOT mean a capability is missing — it just
  means it's one `describe_tool` or `load_toolset` call away.
```

## `RUNTIME_TOOLSET_UNSCOPED`

_Tail block appended when ``JAEGER_TOOLSET_SCOPING`` is OFF (every registered tool already visible)._

```text
- The full built-in tool surface is visible. Pick the specific tool that
  matches the request; do not call `load_toolset` unless you are explicitly
  asked to inspect or widen toolsets.
```

