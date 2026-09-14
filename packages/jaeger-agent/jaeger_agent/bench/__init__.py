"""The bench corpus — what this agent is supposed to get right.

Moved here in 1.0.2. The cases measure THIS module's behaviour — routing,
multi-step planning, memory, recovery, file work, skill selection,
injection resistance — so they belong beside the code they measure. While
they lived in JaegerAI, jaeger-agent could not run its own regression
suite: a change to tool bundles or the context guard shipped with 375
unit tests behind it and no routing signal at all.

CORPUS ONLY, deliberately. The runner stays in the application because it
needs a live agent, an instance layout and a system prompt — a host
adapter this module does not yet define. These files are pure data with
no imports beyond ``__future__``, which is exactly why they could move
today and the runner could not.

Scenario authoring (``scenarios.py``) also stays: it builds Manifests and
InstanceLayouts, which are application shapes.
"""

from __future__ import annotations

from .cases import BENCHMARK_VERSION, CASES, UMBRELLA_EQUIVALENTS, BenchCase, all_tags

__all__ = ["BENCHMARK_VERSION", "CASES", "UMBRELLA_EQUIVALENTS", "BenchCase", "all_tags"]
