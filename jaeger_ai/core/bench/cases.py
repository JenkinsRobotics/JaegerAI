"""The bench corpus now lives in jaeger-agent.

Moved in jaeger-agent 1.0.2 / JaegerAI 0.11.0. The cases measure the
AGENT's behaviour — routing, multi-step, memory, recovery — so they
belong beside the code they measure, and the module needs them to have
any regression signal of its own.

This shim re-exports them so every existing import keeps working. The
runner and the scenario builders stay here: they need a live agent, an
instance layout and a system prompt, none of which the module can supply
itself yet.
"""

from __future__ import annotations

from jaeger_agent.bench.cases import (  # noqa: F401
    CASES,
    UMBRELLA_EQUIVALENTS,
    BenchCase,
    all_tags,
)

__all__ = ["CASES", "UMBRELLA_EQUIVALENTS", "BenchCase", "all_tags"]
