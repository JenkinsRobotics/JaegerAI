"""Repair backlog mirrors from durable hub messages and native handoffs."""
from __future__ import annotations

import json
import logging

from .store import BacklogStore, record_hub_message

logger = logging.getLogger(__name__)
TERMINAL = {"completed": "done", "failed": "failed", "cancelled": "cancelled", "denied": "denied", "rejected": "denied"}


def native_worker(agent_id: str) -> str:
    """Keep the canonical native namespace distinct from hub caller names."""
    from .store import WORKER_RE
    if not isinstance(agent_id, str) or not agent_id.startswith("native:"):
        return ""
    name = agent_id.removeprefix("native:")
    worker = f"native-{name}"
    return worker if WORKER_RE.fullmatch(worker) else ""


def record_native_handoff(store: BacklogStore, record: dict) -> dict | None:
    """Mirror a native record by immutable ID; repeated calls do not touch timestamps."""
    handoff_id = str(record.get("id") or "")
    worker = native_worker(record.get("to_agent_id"))
    if not handoff_id or not worker:
        return None
    status = str(record.get("status") or "")
    result = TERMINAL.get(status)
    desired = "needs_ok" if status == "pending_approval" or result in ("failed", "denied") else (
        "done" if result in ("done", "cancelled") else "in_progress")
    task = store.by_handoff(handoff_id)
    if task is None:
        task = store.add((record.get("task") or "Native handoff")[:300],
                         detail=(record.get("task") or "")[:8000], source="native-handoff",
                         status=desired, worker=worker, import_key=f"native-handoff:{handoff_id}")
    changes = {"handoff_id": handoff_id, "worker": worker,
               "last_note": status[:500]}
    if result:
        changes["handoff_result"] = result
    # Do not reverse an explicitly completed backlog task on an older event.
    if task["status"] != "done" or desired == "done":
        changes["status"] = desired
    changes = {key: value for key, value in changes.items() if task.get(key) != value}
    return store.update(task["id"], **changes) if changes else task


def reconcile(store: BacklogStore, gateway_store, *, apply: bool = False) -> dict:
    """Compare all durable records; apply changes only when requested."""
    with gateway_store._get_conn() as conn:
        messages = [json.loads(row["payload"]) for row in conn.execute(
            "SELECT payload FROM agent_messages ORDER BY seq")]
    handoffs = list(reversed(gateway_store.list_handoffs()))
    # Dry runs use a temporary database so the same adapter computes actual diffs.
    if not apply:
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            shadow = BacklogStore(Path(folder) / "backlog.sqlite3")
            with store._conn() as src, shadow._conn() as dst:
                src.backup(dst)
            return _replay(shadow, messages, handoffs)
    return _replay(store, messages, handoffs)


def _replay(store, messages, handoffs):
    changed = []
    for message in messages:
        sender = message.get("from") or message.get("sender") or ""
        try:
            before = store.by_handoff(message.get("reply_to") or message.get("id"), message.get("thread"))
            after = record_hub_message(store, sender, message)
            if after and after != before:
                changed.append(after["id"])
        except Exception:
            logger.warning("Backlog hub reconciliation failed for %s", message.get("id"), exc_info=True)
    for handoff in handoffs:
        try:
            before = store.by_handoff(handoff.get("id"))
            after = record_native_handoff(store, handoff)
            if after and after != before:
                changed.append(after["id"])
        except Exception:
            logger.warning("Backlog native reconciliation failed for %s", handoff.get("id"), exc_info=True)
    return {"changed": sorted(set(changed)), "message_count": len(messages), "handoff_count": len(handoffs)}
