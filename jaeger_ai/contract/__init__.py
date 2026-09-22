"""jaeger_ai.contract — facts two layers must agree on.

A value that lives in two places eventually disagrees with itself, and the
disagreement is invisible: both files look right, the code runs, and only the
behaviour is wrong. Every bug this package was created to prevent had that
shape — a roster that routed to the wrong framework, a port constant with two
different values under one name, a profile called ``default`` in one layer and
``hermes`` in the next.

So: if a fact is known by more than one layer, it is defined here, once, and
imported. Never re-derived, never re-typed.

* :mod:`~jaeger_ai.contract.frameworks` — the four backends a turn can run on,
  and every name each one answers to.
* :mod:`~jaeger_ai.contract.ports` — the default port for every service.
* :mod:`~jaeger_ai.contract.sessions` — how a session id encodes the
  framework and surface that created it.

**This package imports nothing from the rest of** ``jaeger_ai``. That is the
rule that makes it safe for any module to import, and it is load-bearing: the
moment ``contract`` depends on something above it, the cycles start and the
constants migrate back out to where they were.

Its sibling is :mod:`jaeger_os.contract`, which owns the engine's wire truth —
bus topics, the NDJSON client protocol and its cross-language fixtures, and
the hardware ports. Engine facts go there; application facts go here. Do not
copy one into the other.
"""
from __future__ import annotations

from . import frameworks, ports, schemas, sessions

__all__ = ["frameworks", "ports", "schemas", "sessions"]
