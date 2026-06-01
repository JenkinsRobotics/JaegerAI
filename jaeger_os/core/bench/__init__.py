"""Agent-callable self-bench.

A flat list of bench cases (routing + multi-step + multi-turn +
recovery) the agent can run against ITS OWN live pipeline via the
``run_benchmark`` tool. No subprocess, no separate model load — every
case exercises the real boot, the real system prompt, the real lean
surface, the real drift parser, the real dispatch path.

This is more honest than the legacy ``benchmark/levels/run_all_levels.py``
harness, which booted a fresh pipeline; the agent-driven version
catches regressions in the surface the user actually talks to.
"""

from .cases import CASES, BenchCase  # noqa: F401
from .runner import BenchRow, run_bench, summarise  # noqa: F401

__all__ = ["BenchCase", "BenchRow", "CASES", "run_bench", "summarise"]
