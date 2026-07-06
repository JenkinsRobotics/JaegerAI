"""Runtime tool-surface notes — the only framework rule constants left in code.

The behavioral framework prompt (what you are, how you work, memory, files,
tools, output) is now a single editable document — ``framework_agent.md``,
loaded by :func:`context_blocks.load_framework_prompt`. The Three Laws safety
contract is ``three_laws.md``, loaded via :mod:`jaeger_os.agent.safety`.

What remains here are the two SHORT, mutually-exclusive tool-surface notes
that :func:`context_blocks.build_runtime_tail` picks between at runtime, based
on whether toolset scoping is active. They stay as constants because the
choice is dynamic (per-turn), not static prompt text.
"""

from __future__ import annotations


RUNTIME_TOOLSET_SCOPED = """\
- You see a small CORE set of tools, NOT every tool. Before you act on a task,
  you MUST `list_tools("<keyword>")` to find the RIGHT tool — do not assume a
  visible CORE tool is the best fit (searching "weather" finds `get_weather`,
  not `web_search`; "speak" finds `text_to_speech`). Then:
    • if the tool you found isn't visible, `load_tools("<its toolset>")` to
      bring it in, THEN use it — `list_tools` tells you which toolset it's in.
    • `describe_tool("name")` peeks at one tool's exact schema without loading.
  Force-fitting a visible tool you didn't look up, or giving up because a tool
  "isn't available", is a FAILURE. Search (`list_tools`), load, then act.
"""


RUNTIME_TOOLSET_UNSCOPED = """\
- The full built-in tool surface is visible. Pick the specific tool that
  matches the request; do not call `load_tools` unless you are explicitly
  asked to inspect or widen toolsets.
"""


__all__ = [
    "RUNTIME_TOOLSET_SCOPED",
    "RUNTIME_TOOLSET_UNSCOPED",
]
