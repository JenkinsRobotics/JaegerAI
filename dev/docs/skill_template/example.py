"""Reference / template skill that ships with Jaeger.

This is NOT a production capability — it's the canonical example showing
the skill contract every NEW skill must follow:

  1. Folder name `<name>_v<N>/` (here: `example_v1`)
  2. A `SKILL.md` documenting what / when / how / depends-on
  3. A Python module (this file) exposing a top-level `register(agent)`
     function that attaches one or more tools via `@agent.tool_plain`
  4. A `tests/smoke_test.py` the loader runs before activating the skill

Copy this folder + edit when you (or the agent) author a new skill.
"""

from __future__ import annotations

from typing import Any


def say_example(name: str = "world") -> dict[str, Any]:
    """Return a greeting. Reference output — not for production use."""
    clean = (name or "world").strip() or "world"
    return {"greeting": f"Hello, {clean}!", "skill": "example_v1"}


def register(agent: Any) -> None:
    """Wire `say_example` onto the agent as a plain tool.

    Pydantic AI infers the schema from the function signature + docstring;
    no extra wiring needed. Skills that want richer types can import their
    own Pydantic models here.
    """
    @agent.tool_plain
    def say_example_greeting(name: str = "world") -> dict[str, Any]:
        """Return a greeting. Reference / template skill — not for production use."""
        return say_example(name=name)
