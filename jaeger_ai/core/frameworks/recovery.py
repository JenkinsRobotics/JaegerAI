"""Operator recovery for durable native runs with unknown outcomes."""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

from jaeger_ai.contract.frameworks import (
    SOLO_RUNTIMES,
    backend_protocol,
    canonical_runtime,
)
from jaeger_ai.core.instance.instance import operator_state_root

from .native_runs import Runs
from .run_ownership import Ownership


def _matching_roots(state_root: Path, runtime: str, run_id: str) -> list[Path]:
    receipt = f"{run_id}.json"
    matches: list[Path] = []
    names = {"table-runs"} if runtime == "roundtable" else {runtime, f"{runtime}-runs"}
    for base, directories, files in os.walk(state_root, followlinks=False):
        directories[:] = [name for name in directories
                          if name != "archive" and not (Path(base) / name).is_symlink()]
        root = Path(base)
        if receipt in files and "ownership.sqlite3" in files:
            if root.name in names:
                matches.append(root)
    return matches


def reconcile_owned_run(runtime: str, run_id: str, *, state_root: Path | None = None) -> dict:
    """Reconcile one exact durable receipt and release only on terminal proof."""
    runtime = canonical_runtime(runtime)
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("run_id must be 32 lowercase hexadecimal characters")
    roots = _matching_roots((state_root or operator_state_root()).resolve(), runtime, run_id)
    if not roots:
        raise FileNotFoundError(f"No owned {runtime} receipt found for run {run_id}")
    if len(roots) != 1:
        raise RuntimeError("Run identity appears in multiple ownership stores; inspect before reconciling")
    if runtime == "roundtable":
        from jaeger_ai.features.roundtable.service import TableService
        result = TableService(roots[0].parent).reconcile(run_id)
    else:
        protocol = backend_protocol(runtime)
        result = Runs(
            roots[0], protocol.turn, reconciler=protocol.reconciler
        ).reconcile(run_id)
    return {**result, "runtime": runtime, "store": str(roots[0])}


def abandon_owned_run(
    runtime: str,
    run_id: str,
    reason: str,
    *,
    state_root: Path | None = None,
) -> dict:
    """Resolve irretrievable evidence by recording an explicit operator override."""
    runtime = canonical_runtime(runtime)
    reason = str(reason or "").strip()
    if len(reason) < 8:
        raise ValueError("abandon requires a specific reason of at least 8 characters")
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("run_id must be 32 lowercase hexadecimal characters")
    roots = _matching_roots((state_root or operator_state_root()).resolve(), runtime, run_id)
    if not roots:
        raise FileNotFoundError(f"No owned {runtime} receipt found for run {run_id}")
    if len(roots) != 1:
        raise RuntimeError("Run identity appears in multiple ownership stores; inspect before abandoning")
    root = roots[0]
    ownership = Ownership(root)
    lease = ownership.observer_lease(run_id)
    try:
        path = root / f"{run_id}.json"
        if path.is_symlink():
            raise RuntimeError("Refusing symlinked native receipt")
        saved = json.loads(path.read_text(encoding="utf-8"))
        with ownership.transaction() as db:
            owner = db.execute(
                "SELECT session FROM owners WHERE run_id=?", (run_id,)
            ).fetchone()
        if owner is None or owner[0] != saved.get("session_id"):
            raise RuntimeError("Ownership receipt changed during recovery; inspect before abandoning")
        evidence = {
            "source": "operator_abandon",
            "reason": reason,
            "recorded_at": time.time(),
            "prior_native": saved.get("native") or {},
        }
        saved.update(
            status="failed",
            terminal_state=saved.get("terminal_state") or "failed",
            execution_unknown=False,
            cancellation_confirmed=False,
            pending_approval_ids=[],
            reconciliation=evidence,
            error=f"Operator abandoned irretrievable native execution: {reason}",
        )
        events = list(saved.get("events") or [])
        events.append({
            "event": "run.abandoned",
            "run_id": run_id,
            "seq": len(events) + 1,
            "reason": reason,
            "source": "operator_abandon",
        })
        saved["events"] = events
        saved["last_event_id"] = f"{run_id}:{len(events)}"
        temporary = path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(saved, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        ownership.release(run_id)
        try:
            from jaeger_ai.features.webui.service.session_unify import close_reconciled_webui_session
            close_reconciled_webui_session(str(saved.get("session_id") or ""))
        except Exception:
            pass
        return {
            "run_id": run_id,
            "session_id": saved.get("session_id"),
            "status": saved["status"],
            "execution_unknown": False,
            "reconciliation": evidence,
            "runtime": runtime,
            "store": str(root),
        }
    finally:
        os.close(lease)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jaeger runs",
        description="Resolve durable unknown native runs without redispatching them.",
    )
    parser.add_argument("action", choices=("reconcile", "abandon"))
    parser.add_argument("runtime", choices=(*SOLO_RUNTIMES, "roundtable"))
    parser.add_argument("run_id")
    parser.add_argument("--reason", default="")
    args = parser.parse_args(argv)
    try:
        if args.action == "reconcile":
            result = reconcile_owned_run(args.runtime, args.run_id)
        else:
            result = abandon_owned_run(args.runtime, args.run_id, args.reason)
        print(json.dumps(result, indent=2, sort_keys=True))
    except Exception as exc:
        parser.exit(1, f"jaeger runs {args.action}: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
