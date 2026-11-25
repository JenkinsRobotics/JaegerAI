"""Developer quality & safety tools backed by ``jaeger-lsp`` and ``jaeger-checkpoints``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jaeger_tools.tool_registry import register_tool_from_function


def _checkpoint_store():
    from jaeger_checkpoints import ShadowCheckpointStore
    root = Path.home() / ".jaeger" / "checkpoints"
    return ShadowCheckpointStore(root)


@register_tool_from_function(name="check_diagnostics", side_effect="read")
def check_diagnostics(path: str) -> dict[str, Any]:
    """Run fast syntax/lint diagnostics (Python, JSON, JS, Swift) on an edited file."""
    from jaeger_lsp import check_file_diagnostics
    return check_file_diagnostics(path).to_dict()


@register_tool_from_function(name="checkpoint_snapshot", side_effect="write")
def checkpoint_snapshot(workspace: str, label: str = "checkpoint") -> dict[str, Any]:
    """Save an isolated shadow-Git snapshot of ``workspace`` without touching its ``.git``."""
    try:
        cp = _checkpoint_store().snapshot(workspace, label=label)
        return {
            "ok": True,
            "checkpoint_id": cp.checkpoint_id,
            "workspace": cp.workspace,
            "label": cp.label,
            "timestamp": cp.timestamp,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@register_tool_from_function(name="checkpoint_diff", side_effect="read")
def checkpoint_diff(workspace: str, checkpoint_id: str) -> dict[str, Any]:
    """Show the unified diff between ``workspace`` and a prior shadow-Git checkpoint."""
    try:
        diff_text = _checkpoint_store().diff(workspace, checkpoint_id)
        return {"ok": True, "checkpoint_id": checkpoint_id, "diff": diff_text[:12_000], "truncated": len(diff_text) > 12_000}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@register_tool_from_function(name="checkpoint_restore", side_effect="write")
def checkpoint_restore(workspace: str, checkpoint_id: str) -> dict[str, Any]:
    """Restore ``workspace`` to a prior shadow-Git checkpoint (auto-saves an undo snapshot first)."""
    try:
        return _checkpoint_store().restore(workspace, checkpoint_id)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


__all__ = [
    "check_diagnostics",
    "checkpoint_snapshot",
    "checkpoint_diff",
    "checkpoint_restore",
]
