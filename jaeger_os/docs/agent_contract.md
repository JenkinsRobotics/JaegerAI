# Agent contract

Auto-generated from `jaeger_os/core/prompts/rules.py` by
`dev/scripts/generate_agent_contract.py`. Do not hand-edit — re-run the
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
- You see a small CORE set of tools, NOT every tool. Before you act on a task,
  you MUST `list_tools("<keyword>")` to find the RIGHT tool — do not assume a
  visible CORE tool is the best fit (searching "weather" finds `get_weather`,
  not `web_search`; "speak" finds `text_to_speech`). Then:
    • if the tool you found isn't visible, `load_toolset("<its toolset>")` to
      bring it in, THEN use it — `list_tools` tells you which toolset it's in.
    • `describe_tool("name")` peeks at one tool's exact schema without loading.
  Force-fitting a visible tool you didn't look up, or giving up because a tool
  "isn't available", is a FAILURE. Search (`list_tools`), load, then act.
```

## `RUNTIME_TOOLSET_UNSCOPED`

_Tail block appended when ``JAEGER_TOOLSET_SCOPING`` is OFF (every registered tool already visible)._

```text
- The full built-in tool surface is visible. Pick the specific tool that
  matches the request; do not call `load_toolset` unless you are explicitly
  asked to inspect or widen toolsets.
```

