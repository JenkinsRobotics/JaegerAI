"""Native work ledger — the agent's structured progress book.

A long batch ("process these 300 items") fails in two boring ways: the
model loses count and takes a shortcut, or it *claims* the job is done
while half the list is still untouched. This module is the observable
counter those failure modes cannot lie about.

Two tools:

  * ``work_ledger`` — create / update / status. Persisted under the
    instance ``run/`` dir so a crash does not forget the tally.
  * ``complete_task`` — the only successful exit for an autonomous
    run. Refuses to settle unless every ledger item is marked done.

The ledger is also rendered as a context block and prepended to each
turn so the model sees the count even after compaction has flushed the
raw tool JSON that produced it.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from jaeger_os.core.tools.tool_registry import register_tool_from_function


LEDGER_TAG = "[Work Ledger]"

_lock = threading.RLock()
# Thread-local so a background worker's ledger is not the main
# session's, and two workers can tally in parallel. ``_by_id`` is the
# process-wide inspect surface: the main agent calls
# ``work_ledger(action="status", task_id=...)`` to read a worker's
# progress without sharing its thread.
_tls = threading.local()
_by_id: dict[str, WorkLedger] = {}
# Optional process-wide verifier. Tests and hosts can register a
# callable ``(WorkLedger) -> error|None``. The ledger-attached
# ``verify`` spec is the normal path; this is the escape hatch.
_completion_verifier: Callable[["WorkLedger"], str | None] | None = None
# Live UI progress. The boot path installs a publisher that forwards
# ``tool.progress`` frames; tests capture the same dict. ``reset()``
# does not clear this — /new must not silence the drawer.
_progress_publisher: Callable[..., None] | None = None
_PATHISH = re.compile(r"[/\\]|\.(txt|md|json|py|csv|log)$", re.IGNORECASE)


@dataclass
class WorkLedger:
    """One autonomous task's item-level progress."""

    task_id: str
    task_name: str
    total_items: int = 0
    completed_ids: list[str] = field(default_factory=list)
    in_progress_ids: list[str] = field(default_factory=list)
    remaining_ids: list[str] = field(default_factory=list)
    remaining_count: int | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed: bool = False
    summary: str = ""
    evidence: str = ""
    verification_receipts: list[dict[str, Any]] = field(default_factory=list)
    # Fail-closed verification attached at create. ``None`` means
    # count-only. ``{"kind": "paths_exist", "paths": [...]}`` checks
    # those files are on disk before complete_task can succeed.
    verify: dict[str, Any] | None = None

    def done_count(self) -> int:
        return len(self._dedupe(self.completed_ids))

    def remaining(self) -> int:
        if self.remaining_count is not None:
            return max(0, int(self.remaining_count))
        if self.remaining_ids:
            return len(self._dedupe(self.remaining_ids))
        total = int(self.total_items or 0)
        if total > 0:
            return max(0, total - self.done_count() - len(self._dedupe(self.in_progress_ids)))
        return 0

    def total(self) -> int:
        if int(self.total_items or 0) > 0:
            return int(self.total_items)
        return self.done_count() + len(self._dedupe(self.in_progress_ids)) + self.remaining()

    def unfinished_reason(self) -> str | None:
        """Why ``complete_task`` must refuse, or ``None`` when every
        item is marked done."""
        in_progress = self._dedupe(self.in_progress_ids)
        if in_progress:
            return (
                f"{len(in_progress)} item(s) still in progress: "
                + ", ".join(in_progress[:8])
            )
        leftover = self.remaining()
        if leftover > 0:
            return f"{leftover} item(s) still remaining"
        total = self.total()
        done = self.done_count()
        if total > 0 and done < total:
            return f"ledger shows {done}/{total} completed"
        if total <= 0:
            return "ledger has no countable items — complete_task refused (fail closed)"
        return None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["done_count"] = self.done_count()
        payload["remaining"] = self.remaining()
        payload["total"] = self.total()
        return payload

    def context_block(self) -> str:
        done, total = self.done_count(), self.total()
        remaining = self.remaining()
        in_progress = self._dedupe(self.in_progress_ids)
        lines = [
            LEDGER_TAG,
            f"task_id: {self.task_id}",
            f"task: {self.task_name}",
            f"progress: {done}/{total} completed, {remaining} remaining",
        ]
        if in_progress:
            lines.append("in_progress: " + ", ".join(in_progress[:12]))
        remaining_ids = self._dedupe(self.remaining_ids)
        if remaining_ids:
            preview = remaining_ids[:12]
            more = f" (+{len(remaining_ids) - 12} more)" if len(remaining_ids) > 12 else ""
            lines.append("remaining_ids: " + ", ".join(preview) + more)
        completed = self._dedupe(self.completed_ids)
        if completed:
            preview = completed[-8:]
            lines.append("recently_completed: " + ", ".join(preview))
        if self.completed:
            lines.append("status: COMPLETE")
        else:
            lines.append("status: IN PROGRESS — do not stop until complete_task succeeds")
        return "\n".join(lines)

    @staticmethod
    def _dedupe(values: list[str] | None) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for raw in values or []:
            item = str(raw).strip()
            if not item or item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out


def _tls_active() -> WorkLedger | None:
    return getattr(_tls, "active", None)


def _tls_completion() -> dict[str, Any] | None:
    payload = getattr(_tls, "completion", None)
    return dict(payload) if payload else None


def _set_tls_active(ledger: WorkLedger | None) -> None:
    _tls.active = ledger


def _set_tls_completion(payload: dict[str, Any] | None) -> None:
    _tls.completion = payload


def active_ledger() -> WorkLedger | None:
    return _tls_active()


def last_completion() -> dict[str, Any] | None:
    return _tls_completion()


def consume_completion() -> dict[str, Any] | None:
    """Return and clear this thread's most recent successful ``complete_task``."""
    payload = _tls_completion()
    _set_tls_completion(None)
    return payload


def context_block() -> str:
    ledger = active_ledger()
    if ledger is None or ledger.completed:
        return ""
    return ledger.context_block()


def all_ledgers() -> list[WorkLedger]:
    with _lock:
        return list(_by_id.values())


def get_ledger(task_id: str) -> WorkLedger | None:
    ident = (task_id or "").strip()
    if not ident:
        return None
    with _lock:
        found = _by_id.get(ident)
    if found is not None:
        return found
    return _load(ident)


def set_completion_verifier(
    fn: Callable[[WorkLedger], str | None] | None,
) -> None:
    """Register (or clear) a process-wide completion verifier.

    The callable returns an error string to refuse ``complete_task``,
    or ``None`` to allow it. Checked after the ledger-attached spec.
    """
    global _completion_verifier
    _completion_verifier = fn


def set_progress_publisher(fn: Callable[..., None] | None) -> None:
    """Register (or clear) the live-progress sink.

    The boot path installs a publisher that emits ``tool.progress``
    frames for the chat drawer and the hotkey HUD. Tests pass a list
    append. ``reset()`` does not clear this.
    """
    global _progress_publisher
    _progress_publisher = fn


def progress_event(
    ledger: WorkLedger | None = None,
    *,
    state: str = "RUNNING",
    step: int | None = None,
    phase: str | None = None,
) -> dict[str, Any]:
    """Wire payload for one live-progress frame.

    ``detail`` stays a short human line (``notes · 190/292 · item_190``)
    so older shells still render something. ``args`` is the structured
    snapshot the Swift drawer parses.
    """
    snap = {} if ledger is None else ledger.as_dict()
    done = int(snap.get("done_count") or 0)
    total = int(snap.get("total") or 0)
    remaining = int(snap.get("remaining") or 0)
    name = str(snap.get("task_name") or "")
    in_progress = [str(i) for i in (snap.get("in_progress_ids") or []) if str(i)]
    completed = bool(snap.get("completed"))
    if completed:
        state = "COMPLETED"
    if phase is None:
        phase = "done" if completed else "progress"
    current = in_progress[0] if in_progress else ""
    if total:
        detail = f"{done}/{total}"
    elif step is not None:
        detail = f"step {step}"
    else:
        detail = "running"
    if name:
        detail = f"{name} · {detail}"
    if current:
        detail = f"{detail} · {current}"
    args: dict[str, Any] = {
        "task_id": str(snap.get("task_id") or ""),
        "task_name": name,
        "done": done,
        "total": total,
        "remaining": remaining,
        "in_progress": in_progress,
        "completed": completed,
        "state": state,
    }
    if step is not None:
        args["step"] = int(step)
    return {
        "name": "work_ledger",
        "phase": phase,
        "elapsed_s": 0.0,
        "detail": detail,
        "args": args,
    }


def _emit_progress(
    ledger: WorkLedger | None,
    *,
    state: str = "RUNNING",
    step: int | None = None,
    phase: str | None = None,
) -> None:
    fn = _progress_publisher
    if fn is None:
        return
    try:
        fn(**progress_event(ledger, state=state, step=step, phase=phase))
    except Exception:  # noqa: BLE001 — the drawer must never take a turn down
        return


def reset() -> None:
    """Drop in-memory ledger state. Tests and ``/new`` use this."""
    global _completion_verifier
    _set_tls_active(None)
    _set_tls_completion(None)
    _completion_verifier = None
    with _lock:
        _by_id.clear()


def _layout_run_dir() -> Path | None:
    try:
        from jaeger_ai.main import _pipeline
        layout = _pipeline.get("layout")
        root = getattr(layout, "root", None)
        if root is None:
            return None
        run_dir = getattr(layout, "run_dir", None)
        path = Path(str(run_dir)) if run_dir is not None else Path(str(root)) / "run"
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:  # noqa: BLE001 — persistence is best-effort
        return None


def _ledger_path(task_id: str) -> Path | None:
    run_dir = _layout_run_dir()
    if run_dir is None:
        return None
    safe = "".join(ch for ch in task_id if ch.isalnum() or ch in "-_") or "task"
    return run_dir / f"ledger_{safe}.json"


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _persist(ledger: WorkLedger) -> None:
    with _lock:
        _by_id[ledger.task_id] = ledger
    path = _ledger_path(ledger.task_id)
    if path is None:
        return
    try:
        _atomic_write(path, json.dumps(ledger.as_dict(), indent=2, sort_keys=False))
    except OSError:
        return


def _load(task_id: str) -> WorkLedger | None:
    path = _ledger_path(task_id)
    if path is None or not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(raw, dict) or not raw.get("task_id"):
        return None
    ledger = WorkLedger(
        task_id=str(raw.get("task_id") or task_id),
        task_name=str(raw.get("task_name") or ""),
        total_items=int(raw.get("total_items") or 0),
        completed_ids=WorkLedger._dedupe(_ids(raw.get("completed_ids"))),
        in_progress_ids=WorkLedger._dedupe(_ids(raw.get("in_progress_ids"))),
        remaining_ids=WorkLedger._dedupe(_ids(raw.get("remaining_ids"))),
        remaining_count=raw.get("remaining_count"),
        created_at=float(raw.get("created_at") or time.time()),
        updated_at=float(raw.get("updated_at") or time.time()),
        completed=bool(raw.get("completed")),
        summary=str(raw.get("summary") or ""),
        evidence=str(raw.get("evidence") or ""),
        verification_receipts=[
            dict(item) for item in (raw.get("verification_receipts") or [])
            if isinstance(item, dict)
        ],
        verify=raw.get("verify") if isinstance(raw.get("verify"), dict) else None,
    )
    with _lock:
        _by_id[ledger.task_id] = ledger
    return ledger


def _ids(value: Any) -> list[str]:
    """Normalize an id bucket into a clean list of strings.

    A model routinely hands these lists over as a JSON-encoded STRING
    (``'["item_00.txt", "item_01.txt"]'``) rather than a native array —
    Qwen and GLM both do it on ``work_ledger(action="update")``. Splitting
    that on commas kept the bracket and quote characters glued to the
    first and last ids, and an id containing a comma inflated the count,
    which is how a ledger reports a total it never actually reached. Try
    JSON first; fall back to comma-splitting for a genuine
    ``"a, b, c"`` string.
    """
    if value is None:
        return []
    if isinstance(value, str):
        body = value.strip()
        if body.startswith("[") and body.endswith("]"):
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        raw = [part.strip() for part in body.split(",")]
        return [part for part in raw if part]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _new_task_id() -> str:
    return uuid.uuid4().hex[:12]


def _resolve_verify_path(raw: str) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        from jaeger_agent.workspace import _resolve_write
        return _resolve_write(text)
    except Exception:  # noqa: BLE001 — unbound layout or sandbox miss
        return Path(text).expanduser()


def _verify_paths_exist(paths: list[str]) -> str | None:
    missing: list[str] = []
    for raw in paths:
        resolved = _resolve_verify_path(raw)
        if resolved is None or not resolved.exists():
            missing.append(str(raw))
    if missing:
        preview = ", ".join(missing[:8])
        extra = f" (+{len(missing) - 8} more)" if len(missing) > 8 else ""
        return f"verification failed — missing {len(missing)} path(s): {preview}{extra}"
    return None


def _run_verification(ledger: WorkLedger) -> str | None:
    """Fail-closed checks. Returns an error string, or None if the
    ledger may complete."""
    reason = ledger.unfinished_reason()
    if reason:
        return reason
    spec = ledger.verify if isinstance(ledger.verify, dict) else None
    if spec:
        kind = str(spec.get("kind") or "").strip().lower()
        if kind == "paths_exist":
            paths = [str(p) for p in (spec.get("paths") or []) if str(p).strip()]
            if not paths:
                return "verify.paths_exist has no paths — fail closed"
            failed = _verify_paths_exist(paths)
            if failed:
                return failed
        elif kind and kind != "count":
            return f"unknown verify kind {kind!r} — fail closed"
    pathish = [i for i in ledger._dedupe(ledger.completed_ids) if _PATHISH.search(i)]
    if pathish:
        failed = _verify_paths_exist(pathish)
        if failed:
            return failed
    if _completion_verifier is not None:
        try:
            extra = _completion_verifier(ledger)
        except Exception as exc:  # noqa: BLE001 — a broken verifier must not complete
            return f"completion verifier raised {type(exc).__name__}: {exc}"
        if extra:
            return str(extra)
    return None


def _verification_receipts(ledger: WorkLedger) -> list[dict[str, Any]]:
    """Create machine-derived completion receipts after checks pass."""
    receipts: list[dict[str, Any]] = [{
        "kind": "ledger_count",
        "done": ledger.done_count(),
        "total": ledger.total(),
        "remaining": ledger.remaining(),
    }]
    spec = ledger.verify if isinstance(ledger.verify, dict) else None
    if spec and str(spec.get("kind") or "").strip().lower() == "paths_exist":
        for raw in [str(p) for p in (spec.get("paths") or []) if str(p).strip()]:
            resolved = _resolve_verify_path(raw)
            if resolved is None or not resolved.is_file():
                receipts.append({"kind": "path_exists", "path": raw, "exists": bool(resolved and resolved.exists())})
                continue
            try:
                digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
                receipts.append({
                    "kind": "file_sha256", "path": raw,
                    "bytes": resolved.stat().st_size, "sha256": digest,
                })
            except OSError:
                receipts.append({"kind": "path_exists", "path": raw, "exists": True})
    return receipts


def work_ledger(
    action: str = "status",
    task_name: str = "",
    task_id: str | None = None,
    total_items: int | None = None,
    completed_ids: list[str] | str | None = None,
    in_progress_ids: list[str] | str | None = None,
    remaining_ids: list[str] | str | None = None,
    remaining_count: int | None = None,
    verify: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create, update, or read the structured work ledger for a long task.

    ``action`` is ``create``, ``update``, or ``status``. The ledger is
    the count of record for batch work — update it as items move, and
    call ``complete_task`` only when every item is in ``completed_ids``.
    """
    verb = (action or "status").strip().lower()
    if verb not in {"create", "update", "status"}:
        return {"ok": False, "error": f"unknown action {action!r}; use create, update, or status"}

    ident = (task_id or "").strip()

    if verb == "status":
        if ident:
            found = get_ledger(ident)
            if found is None:
                return {"ok": True, "active": False, "ledger": None, "task_id": ident}
            return {"ok": True, "active": not found.completed, "ledger": found.as_dict()}
        local = active_ledger()
        if local is not None:
            return {"ok": True, "active": not local.completed, "ledger": local.as_dict()}
        ledgers = [item.as_dict() for item in all_ledgers()]
        return {
            "ok": True,
            "active": any(not item.completed for item in all_ledgers()),
            "ledger": ledgers[0] if len(ledgers) == 1 else None,
            "ledgers": ledgers,
        }

    if verb == "create":
        name = (task_name or "").strip()
        if not name:
            return {"ok": False, "error": "task_name is required to create a ledger"}
        new_id = ident or _new_task_id()
        total = int(total_items or 0)
        remaining = remaining_count
        if remaining is None and total > 0:
            remaining = max(0, total - len(_ids(completed_ids)))
        ledger = WorkLedger(
            task_id=new_id,
            task_name=name,
            total_items=total,
            completed_ids=WorkLedger._dedupe(_ids(completed_ids)),
            in_progress_ids=WorkLedger._dedupe(_ids(in_progress_ids)),
            remaining_ids=WorkLedger._dedupe(_ids(remaining_ids)),
            remaining_count=remaining,
            verify=dict(verify) if isinstance(verify, dict) else None,
        )
        _set_tls_active(ledger)
        _persist(ledger)
        _emit_progress(ledger, state="RUNNING", phase="progress")
        return {"ok": True, "action": "create", "ledger": ledger.as_dict()}

    current = active_ledger()
    if ident and (current is None or ident != current.task_id):
        current = get_ledger(ident)
        if current is not None:
            _set_tls_active(current)
    if current is None:
        return {"ok": False, "error": "no active ledger — call work_ledger(action='create') first"}
    if ident and ident != current.task_id:
        return {
            "ok": False,
            "error": f"task_id {ident!r} does not match the active ledger {current.task_id}",
        }
    if task_name and task_name.strip():
        current.task_name = task_name.strip()
    if total_items is not None:
        current.total_items = int(total_items)
    if completed_ids is not None:
        current.completed_ids = WorkLedger._dedupe(_ids(completed_ids))
    if in_progress_ids is not None:
        current.in_progress_ids = WorkLedger._dedupe(_ids(in_progress_ids))
    if remaining_ids is not None:
        current.remaining_ids = WorkLedger._dedupe(_ids(remaining_ids))
    if verify is not None:
        current.verify = dict(verify) if isinstance(verify, dict) else None
    if remaining_count is not None:
        current.remaining_count = int(remaining_count)
    elif current.total_items:
        current.remaining_count = max(
            0,
            int(current.total_items)
            - current.done_count()
            - len(current._dedupe(current.in_progress_ids)),
        )
    current.updated_at = time.time()
    _persist(current)
    _emit_progress(current, state="RUNNING", phase="progress")
    return {"ok": True, "action": "update", "ledger": current.as_dict()}


def complete_task(
    task_id: str = "",
    summary: str = "",
    evidence: str = "",
) -> dict[str, Any]:
    """Mark an autonomous task complete. Succeeds only when the ledger
    shows every item finished; the outer loop will not settle on a
    prose claim of completion."""
    ident = (task_id or "").strip()
    proof = (evidence or "").strip()
    if not proof:
        return {
            "ok": False,
            "completed": False,
            "error": "evidence is required — cite what was produced or checked",
        }
    current = active_ledger()
    if ident and (current is None or ident != current.task_id):
        current = get_ledger(ident)
        if current is not None:
            _set_tls_active(current)
    if current is None:
        return {"ok": False, "completed": False, "error": "no active work ledger"}
    if ident and ident != current.task_id:
        return {
            "ok": False,
            "completed": False,
            "error": f"task_id {ident!r} does not match the active ledger {current.task_id}",
        }
    reason = _run_verification(current)
    if reason is not None:
        return {
            "ok": False,
            "completed": False,
            "error": f"ledger is not finished: {reason}",
            "ledger": current.as_dict(),
        }
    current.completed = True
    current.summary = (summary or "").strip()
    current.evidence = proof
    current.verification_receipts = _verification_receipts(current)
    current.updated_at = time.time()
    _persist(current)
    payload = {
        "ok": True,
        "completed": True,
        "task_id": current.task_id,
        "summary": current.summary,
        "evidence": proof,
        "verification_receipts": list(current.verification_receipts),
        "ledger": current.as_dict(),
    }
    _set_tls_completion(payload)
    _emit_progress(current, state="COMPLETED", phase="done")
    return payload


# Importing this module registers the two tools — same pattern as
# ``code_bridge_tool``. ``_register_builtins`` pulls the import so a
# boot that never otherwise touches the ledger still has the tools.
@register_tool_from_function(name="work_ledger", side_effect="write")
def _reject_raw(kwargs: dict[str, Any]) -> dict[str, Any] | None:
    if "_raw_arguments" in kwargs:
        return {
            "ok": False,
            "error": "arguments were truncated or unparsed; retry with complete JSON",
            "retryable": True,
        }
    return None


def _t_work_ledger(
    action: str = "status",
    task_name: str = "",
    task_id: str | None = None,
    total_items: int | None = None,
    completed_ids: list[str] | str | None = None,
    in_progress_ids: list[str] | str | None = None,
    remaining_ids: list[str] | str | None = None,
    remaining_count: int | None = None,
    verify: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict:
    """Track structured progress on a multi-item or long-running task.

    Use this whenever the work has a countable set of items (files,
    rows, notes, records). ``action="create"`` opens a ledger with
    ``task_name`` and ``total_items``. ``action="update"`` replaces the
    completed / in-progress / remaining lists as you go. ``action="status"``
    returns the current counts. The ledger is re-injected every turn;
    it is the count of record — do not guess progress from memory.
    """
    refused = _reject_raw(kwargs)
    if refused:
        return refused
    return work_ledger(
        action=action,
        task_name=task_name,
        task_id=task_id,
        total_items=total_items,
        completed_ids=completed_ids,
        in_progress_ids=in_progress_ids,
        remaining_ids=remaining_ids,
        remaining_count=remaining_count,
        verify=verify,
    )


@register_tool_from_function(name="complete_task", side_effect="write")
def _t_complete_task(
    task_id: str = "", summary: str = "", evidence: str = "", **kwargs: Any,
) -> dict:
    """Declare an autonomous task finished. This is the only successful
    way a goal-driven run ends. ``evidence`` must describe what was
    produced or verified. Refuses if the work ledger still has remaining
    or in-progress items, or if attached verification fails.
    """
    refused = _reject_raw(kwargs)
    if refused:
        return refused
    return complete_task(task_id=task_id, summary=summary, evidence=evidence)


__all__ = [
    "LEDGER_TAG",
    "WorkLedger",
    "active_ledger",
    "all_ledgers",
    "get_ledger",
    "last_completion",
    "consume_completion",
    "context_block",
    "reset",
    "set_completion_verifier",
    "set_progress_publisher",
    "progress_event",
    "work_ledger",
    "complete_task",
]
