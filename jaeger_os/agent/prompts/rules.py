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
"""


RUNTIME_TOOLSET_UNSCOPED = """\
- The full built-in tool surface is visible. Pick the specific tool that
  matches the request; do not call `load_toolset` unless you are explicitly
  asked to inspect or widen toolsets.
"""


__all__ = [
    "RUNTIME_TOOLSET_SCOPED",
    "RUNTIME_TOOLSET_UNSCOPED",
]
