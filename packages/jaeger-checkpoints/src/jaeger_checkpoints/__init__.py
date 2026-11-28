"""jaeger-checkpoints — Shadow-Git per-step workspace checkpoints, rollback & TurnDiffTracker."""

from . import shadow_manager
from .shadow_manager import (
    CheckpointManager,
    SnapshotRecord,
    configure_checkpoints,
    manager,
    reset_manager,
    store_path,
)
from .store import Checkpoint, ShadowCheckpointStore
from .turn_diff import TurnDiffTracker

__all__ = [
    "Checkpoint",
    "CheckpointManager",
    "ShadowCheckpointStore",
    "SnapshotRecord",
    "TurnDiffTracker",
    "configure_checkpoints",
    "manager",
    "reset_manager",
    "shadow_manager",
    "store_path",
]
