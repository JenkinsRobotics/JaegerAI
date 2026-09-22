"""jaeger_ai.core.context_compiler — Canonical Context Compiler.

Translates persistent agent memory, observations, reflections, and skills into
bounded, provenance-tagged model context according to cognition profiles.
"""
from __future__ import annotations

from .compiler import ContextCompiler
from .models import CompiledContext, ContextItem
from .provenance import MemoryProvenance

__all__ = [
    "ContextCompiler",
    "CompiledContext",
    "ContextItem",
    "MemoryProvenance",
]
