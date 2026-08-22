"""Host seams — none left. Kept as the guard that keeps it that way.

The 0.11 move brought the agent surface across from JaegerAI, and about
fourteen call sites still reached back for something the module did not
own: a memory backend, a credential store, a venv manager, a lazy-dep
gate, a refusal detector. Each was bound through :func:`host_required`
so the package still imported with no host installed and only the
individual tool failed.

That list is now empty, and it emptied in two different ways:

  MOVED IN — they were agent infrastructure sitting in an application.
    jaeger_agent/memory/             conversation + fact memory (1,796 lines)
    jaeger_agent/credentials.py      the secret store
    jaeger_agent/skill_improvement/  skill notes and revisions
    jaeger_agent/util/venv.py        per-skill virtualenvs
    jaeger_agent/util/lazy_deps.py   the optional-dependency gate
    prompts/persona_lane._is_refusal three lines and a word list

  MOVED OUT — they were product features sitting in the agent.
    avatar tools     → jaeger_ai/nodes/animation/tools.py, beside the
                       node whose face they drive
    generate_*_fal   → stayed with JaegerAI's fal.ai plugin; a cloud
                       image generator is not something a robot's brain
                       needs to own

The distinction is the whole test, and it is not "is this useful" —
everything is useful. It is whether the thing needs an application to
mean anything. Memory does not; an avatar does.

:func:`host_required` survives because the next extraction will want it,
and because a lazy binding is the right answer when one genuinely
appears: a missing host should cost one tool, not the package.
"""

from __future__ import annotations

from typing import Any


def host_required(module: str, symbol: str = "") -> Any:
    """A stand-in that raises only if something actually calls it.

    Returned in place of a symbol a host application was supposed to
    provide. Importing stays free; using it names the missing module
    rather than raising an AttributeError on ``None`` three frames away.

    Nothing uses this today — see the module docstring. If you reach for
    it, first ask which direction the thing should move.
    """

    name = f"{module}.{symbol}" if symbol else module

    def _unavailable(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(
            f"{name} is provided by a host application and is not "
            f"installed. Either install the host or inject an equivalent."
        )

    return _unavailable


__all__ = ["host_required"]
