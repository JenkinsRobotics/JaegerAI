"""Stub for deprecated shared_memory feature.

Honcho shared memory is deprecated. Use local memory or Gateway API instead.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class HonchoClient:
    """Stub HonchoClient — always reports unavailable."""
    
    def __init__(self, *args, **kwargs):
        logger.warning(
            "shared_memory (Honcho) is deprecated. "
            "Use local memory or Gateway API instead. "
            "See docs/migration/SHARED_MEMORY.md"
        )
    
    def health(self) -> dict[str, Any]:
        return {"available": False, "reason": "deprecated"}
    
    def close(self) -> None:
        pass


__all__ = ["HonchoClient"]
