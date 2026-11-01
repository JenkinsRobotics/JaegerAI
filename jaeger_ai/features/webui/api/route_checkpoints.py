"""Read-only checkpoint routes bound to the same Gateway workspace as Git."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs

from .helpers import bad, j
from .route_git import _git_session_workspace
from .rollback import get_checkpoint_diff, list_checkpoints

logger = logging.getLogger(__name__)


def handle_checkpoints_get(handler: Any, parsed: Any) -> bool:
    if parsed.path not in ("/api/checkpoints/list", "/api/checkpoints/diff"):
        return False
    qs = parse_qs(parsed.query)
    workspace = _git_session_workspace(handler, qs.get("session_id", [""])[0])
    if workspace is None:
        return True
    try:
        if parsed.path.endswith("/list"):
            result = list_checkpoints(str(workspace), trusted_workspace=True)
            checkpoints = []
            for item in result["checkpoints"]:
                row = {key: item[key] for key in ("id", "message", "date", "date_display", "files")}
                row["files_changed"] = get_checkpoint_diff(
                    str(workspace), item["id"], trusted_workspace=True
                )["total_changes"]
                checkpoints.append(row)
            return j(handler, {"checkpoints": checkpoints})
        checkpoint = qs.get("checkpoint", [""])[0]
        if not checkpoint:
            return bad(handler, "checkpoint required")
        return j(handler, get_checkpoint_diff(str(workspace), checkpoint, trusted_workspace=True))
    except ValueError as exc:
        return bad(handler, str(exc))
    except Exception:
        logger.exception("checkpoint read failed")
        return bad(handler, "Failed to read checkpoints", status=500)
