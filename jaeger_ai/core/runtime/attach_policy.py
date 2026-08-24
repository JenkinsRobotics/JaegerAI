"""Whether this process may attach to a LIVE instance's bridge socket.

Attaching is normally the right thing: one process holds the instance lock
and serves ``run/bridge.sock``, and every other first-party surface shares
that brain instead of booting a second model (see
:mod:`jaeger_ai.core.runtime.bridge_socket`). That is the whole point of the
socket.

It is exactly wrong in one situation: a TEST RUN. ``create_runtime`` tries
the socket BEFORE it tries ``boot_for_tui``, so on a developer machine where
ARES is running, a test that monkeypatches ``boot_for_tui`` never reaches its
own patch — it silently proxies turns to the operator's real agent, against
their real memory, with their real credentials. CI has no live socket, so CI
stays green and only the developer's machine goes red. Two tests were failing
that way (``test_agentcore_prewarm``, ``test_external_agent_runtime``); the
failure was the visible half. The invisible half was that the suite was
talking to production.

The gate is an environment switch rather than an argument threaded through
``create_runtime`` because attachment is decided several frames below every
caller that would have to pass it — ``AgentCore`` → ``create_runtime`` →
``try_attach_runtime`` — and because a caller that forgets to pass it gets
the DANGEROUS default. An environment gate set once for the whole process
fails the other way: the suite is isolated even for code paths nobody
remembered to audit. It mirrors ``JAEGER_NO_GUI``, which the same conftest
already sets for the same reason ("never launch the native app from a test").

Production never sets it, so production behaviour is unchanged.
"""

from __future__ import annotations

import os

__all__ = ["ENV_NO_ATTACH", "attach_disabled", "refusal_note"]

ENV_NO_ATTACH = "JAEGER_NO_ATTACH"

# Accepts the same spellings as the rest of the codebase's boolean env reads.
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def attach_disabled() -> bool:
    """True when this process must NOT connect to a live bridge socket.

    Checked at the single choke point (:func:`~jaeger_ai.core.runtime.attached
    .try_attach_runtime`) rather than at each caller, so a new caller cannot
    reintroduce the hole by forgetting to ask.
    """
    return str(os.environ.get(ENV_NO_ATTACH, "")).strip().lower() in _TRUTHY


def refusal_note() -> str:
    """One line for stderr when an attach is refused, so a developer who hits
    this in a real (non-test) context can tell policy from a dead socket."""
    return (
        f"[jaeger] not attaching to the live agent: {ENV_NO_ATTACH} is set. "
        "Unset it to share a running brain."
    )
