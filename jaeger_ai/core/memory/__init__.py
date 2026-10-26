"""Memory subsystem for JaegerAI.

Includes:
- 5-class memory taxonomy (Working/Episodic/Semantic/Reflective/Procedural)
- Dreaming engine (background consolidation, ported from OpenClaw)
"""

from .dreaming import (
    DreamingEngine,
    DreamPhase,
    DreamCandidate,
    DreamReport,
    run_dreaming,
    get_dreaming_status,
)

__all__ = [
    "DreamingEngine",
    "DreamPhase",
    "DreamCandidate",
    "DreamReport",
    "run_dreaming",
    "get_dreaming_status",
]
