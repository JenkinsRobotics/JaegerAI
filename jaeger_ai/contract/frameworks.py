"""The four frameworks Jaeger can run a turn on — one table, no second copy.

Jaeger routes a conversation to one of four backends. Each one is known by a
different name depending on which layer you are standing in, and that is the
whole problem this module exists to solve:

    runtime      the canonical id used in code           "hermes"
    profile      the WebUI profile name                  "default"   ← not "hermes"
    display_name what a human reads                      "Hermes Agent"
    agent_id     the agent registry's id                 "tp:hermes"
    container    the managed container, when it has one  "jaeger-hermes-webui"

The Hermes row is the trap: its runtime is ``hermes`` but its profile is
``default``, so code that assumes the two words are interchangeable works for
three frameworks out of four and silently misroutes the fourth.

Before this table, that mapping was re-derived in eight places — the WebUI
profile catalogue, the runner's alias dict, the readiness probe's if/else
chain, three container-name dicts, the supervisor's repair table, Roundtable's
member list, and again in JavaScript in the browser. On 2026-09-14 a roster
click routed to the wrong framework precisely because two of those copies
disagreed about what "active" meant.

Nothing here imports the rest of ``jaeger_ai``. It is the bottom layer, on the
same rule as :mod:`jaeger_os.contract` — so any module may import it and none
of them can create a cycle by doing so.
"""
from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from typing import Callable

DEFAULT_AGENT_MODEL = "glm-5.3-flash:cloud"


@dataclass(frozen=True)
class Framework:
    """One backend Jaeger can hand a turn to."""

    runtime: str
    """Canonical id. Use this as the key anywhere code needs to name a backend."""

    profile: str
    """The WebUI profile name. Equals ``runtime`` except for Hermes, which the
    WebUI calls ``default`` because it is the profile you get with no cookie."""

    display_name: str
    """What a person reads. The only string that should ever reach a UI."""

    agent_id: str
    """Id in the agent registry (``~/.jaeger/agents/registry.json``). The prefix
    says where the agent came from: ``native:`` is Jaeger's own, ``tp:`` is a
    third party. Nothing should rebuild this by string-concatenating a prefix."""

    container: str | None = None
    """Managed container name, for backends that run in one."""

    composes: tuple[str, ...] = ()
    """Runtimes this backend delegates to. Only Roundtable has any: it is a
    debate between the other three rather than a backend in its own right,
    which is why it is ready only when all of them are."""

    owns_sessions: bool = True
    """Whether this framework has its own app or terminal that people start
    conversations in, and therefore its own session history.

    The three real backends do — each ships a local app and a CLI, and each
    keeps its own store; Jaeger only indexes them. Roundtable does not: it is
    orchestrated from the WebUI and exists only as browser conversations, so a
    "Roundtable terminal session" is not a thing that can exist."""

    turn: str | None = None
    """Import path for the native ``turn(run, workspace=None)`` callable."""

    reconciler: str | None = None
    """Import path for ``reconcile(native)``. Required when ``turn`` is set."""

    def __post_init__(self) -> None:
        if bool(self.turn) != bool(self.reconciler):
            raise ValueError(
                f"Framework {self.runtime!r} must register turn and reconciler together"
            )


@dataclass(frozen=True)
class BackendProtocol:
    """The required native execution and recovery pair."""

    turn: Callable
    reconciler: Callable


FRAMEWORKS: tuple[Framework, ...] = (
    Framework(
        runtime="hermes",
        profile="default",
        display_name="Hermes Agent",
        agent_id="tp:hermes",
        turn="jaeger_ai.core.frameworks.hermes_native:hermes_turn",
        reconciler="jaeger_ai.core.frameworks.hermes_native:hermes_reconcile",
    ),
    Framework(
        runtime="jaeger",
        profile="jaeger",
        display_name="Jaeger AI",
        agent_id="native:jaeger",
        turn="jaeger_ai.core.frameworks.jaeger:dispatcher_turn",
        reconciler="jaeger_ai.core.frameworks.jaeger:jaeger_reconcile",
    ),
    Framework(
        runtime="openclaw",
        profile="openclaw",
        display_name="OpenClaw",
        agent_id="tp:openclaw",
        container="jaeger-openclaw",
        turn="jaeger_ai.core.frameworks.openclaw_native:openclaw_turn",
        reconciler="jaeger_ai.core.frameworks.openclaw_native:openclaw_reconcile",
    ),
    Framework(
        runtime="roundtable",
        profile="roundtable",
        display_name="Roundtable",
        agent_id="tp:roundtable",
        composes=("jaeger", "hermes", "openclaw"),
        owns_sessions=False,
    ),
)

_BY_RUNTIME = {f.runtime: f for f in FRAMEWORKS}
_BY_PROFILE = {f.profile: f for f in FRAMEWORKS}
_BY_AGENT_ID = {f.agent_id: f for f in FRAMEWORKS}

#: Spellings seen in the wild that mean an existing runtime.
_ALIASES = {"jaegerai": "jaeger", "hermes-webui": "hermes"}

#: The three backends Roundtable debates between, in speaking order.
DEBATE_MEMBERS: tuple[str, ...] = _BY_RUNTIME["roundtable"].composes

#: Runtimes that answer on their own — everything that is not a debate.
SOLO_RUNTIMES: tuple[str, ...] = tuple(f.runtime for f in FRAMEWORKS if not f.composes)

#: Frameworks with their own app/terminal and therefore their own session
#: history. Jaeger indexes these stores; it does not own them.
SESSION_OWNERS: tuple[str, ...] = tuple(f.runtime for f in FRAMEWORKS if f.owns_sessions)


class UnknownFramework(KeyError):
    """Raised for a name that is not one of the four. Carries the valid set."""

    def __init__(self, value: object) -> None:
        super().__init__(
            f"no framework named {value!r}; known runtimes are "
            f"{', '.join(sorted(_BY_RUNTIME))} and profiles are "
            f"{', '.join(sorted(_BY_PROFILE))}"
        )


def canonical_runtime(value: object) -> str:
    """Resolve any spelling — runtime, profile, agent id, alias — to a runtime.

    This is the one place a name is normalised. Case and surrounding whitespace
    are ignored because these values arrive from HTTP bodies and cookies.

    >>> canonical_runtime("default")      # the WebUI's name for Hermes
    'hermes'
    >>> canonical_runtime("tp:openclaw")  # an agent registry id
    'openclaw'
    >>> canonical_runtime(" JaegerAI ")
    'jaeger'
    """
    name = str(value or "").strip().lower()
    if name in _BY_AGENT_ID:
        return _BY_AGENT_ID[name].runtime
    name = _ALIASES.get(name, name)
    if name in _BY_RUNTIME:
        return name
    if name in _BY_PROFILE:
        return _BY_PROFILE[name].runtime
    raise UnknownFramework(value)


def framework(value: object) -> Framework:
    """The :class:`Framework` for any spelling of its name."""
    return _BY_RUNTIME[canonical_runtime(value)]


def profile_name(value: object) -> str:
    """The WebUI profile name for any spelling. ``"hermes"`` → ``"default"``."""
    return framework(value).profile


def display_name(value: object) -> str:
    """The human-facing label for any spelling."""
    return framework(value).display_name


def is_known(value: object) -> bool:
    """Whether ``value`` names one of the four, in any spelling."""
    try:
        canonical_runtime(value)
    except UnknownFramework:
        return False
    return True


def _load_callable(path: str, role: str) -> Callable:
    module_name, separator, attribute = path.partition(":")
    if not separator or not module_name or not attribute:
        raise RuntimeError(f"Invalid {role} import path: {path!r}")
    value = getattr(importlib.import_module(module_name), attribute, None)
    if not callable(value):
        raise RuntimeError(f"Framework {role} is not callable: {path}")
    return value


def backend_protocol(value: object) -> BackendProtocol:
    """Resolve and validate the complete native backend protocol."""
    item = framework(value)
    if not item.turn or not item.reconciler:
        raise RuntimeError(f"Framework {item.runtime!r} has no complete native backend protocol")
    turn = _load_callable(item.turn, "turn")
    reconciler = _load_callable(item.reconciler, "reconciler")
    if not {"run", "workspace"}.issubset(inspect.signature(turn).parameters):
        raise RuntimeError(f"Framework {item.runtime!r} turn must accept run and workspace")
    if "native" not in inspect.signature(reconciler).parameters:
        raise RuntimeError(f"Framework {item.runtime!r} reconciler must accept native")
    return BackendProtocol(turn=turn, reconciler=reconciler)


__all__ = [
    "DEFAULT_AGENT_MODEL",
    "DEBATE_MEMBERS",
    "BackendProtocol",
    "FRAMEWORKS",
    "Framework",
    "SESSION_OWNERS",
    "SOLO_RUNTIMES",
    "UnknownFramework",
    "backend_protocol",
    "canonical_runtime",
    "display_name",
    "framework",
    "is_known",
    "profile_name",
]
