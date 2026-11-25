"""jaeger-memory: SQLite WAL checkpoints+writes, history invariants, context guard, compaction, offloading."""

from . import compactor, context_guard, history
from .compactor import (
    DEFAULT_KEEP_TURNS,
    DEFAULT_THRESHOLD,
    DIGEST_TAG,
    compact_agent,
    compact_messages,
    configure_compactor,
    should_compact,
)
from .context_guard import (
    DIGEST_PREFIX,
    ContextBudget,
    ContextGuard,
    ContextOverflow,
    TrimResult,
    oldest_group_size,
)
from .history import (
    choose_boundary,
    close_dangling_tool_calls,
    replayable_span,
    snap,
)
from .store import (
    GitCheckpointManager,
    RegexTimeoutError,
    SqliteStateMemory,
    ToolOutputOffloader,
    deterministic_resource_id,
    estimate_tokens,
)

__all__ = [
    "ContextBudget",
    "ContextGuard",
    "ContextOverflow",
    "DEFAULT_KEEP_TURNS",
    "DEFAULT_THRESHOLD",
    "DIGEST_PREFIX",
    "DIGEST_TAG",
    "GitCheckpointManager",
    "RegexTimeoutError",
    "SqliteStateMemory",
    "ToolOutputOffloader",
    "TrimResult",
    "choose_boundary",
    "close_dangling_tool_calls",
    "compact_agent",
    "compact_messages",
    "compactor",
    "configure_compactor",
    "context_guard",
    "deterministic_resource_id",
    "estimate_tokens",
    "history",
    "oldest_group_size",
    "replayable_span",
    "should_compact",
    "snap",
]
