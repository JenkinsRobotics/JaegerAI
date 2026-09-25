"""Sub-agent execution — actually running work in another agent.

Sibling of ``delegation.py``, which is a different job: that module normalises
the *arguments* ``delegate_task`` was called with (Jaeger's ``subtasks`` list
vs Hermes's ``goal``/``tasks``). This module runs the result.

Lifted out of ``jaeger_ai/main.py`` on 2026-09-14. It was ~550 lines of one
6,502-line module, and it is self-contained: only ``_register_builtins`` called
into it, and it reads just three things back out of ``main``.

Four ways to hand off work, in rising order of independence:

* ``_delegate_internal``  — another Jaeger agent, same process, inline.
* ``_delegate_external``  — a different runtime entirely (a CLI backend, a peer).
* ``_delegate_background``— durable child work admitted by the Gateway.
* ``_delegate_parallel``  — a fan-out of subtasks, gathered when all finish.

The depth guard (``DELEGATE_MAX_DEPTH``, default 2) is what stops a delegate
from delegating forever.

``_delegate_role`` and ``_llm_lock_held`` are ``threading.local()`` and are
imported back into ``main`` — the same objects, deliberately. ``_llm_lock_held``
records whether THIS thread already holds the LLM lock: a sync delegate runs
inside a locked parent turn and must not re-acquire, while a background worker
runs on a fresh thread and must.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any


def _main():
    """The ``main`` module, resolved at call time.

    Deliberately not a module-level import: ``main`` imports this module, so a
    top-level import here would be a cycle. Going through the module object
    (rather than ``from main import _pipeline``) also means ``_pipeline`` is
    always read live.
    """
    from jaeger_ai import main
    return main


_DELEGATE_MAX_DEPTH = int(os.environ.get("DELEGATE_MAX_DEPTH", "2"))
_delegate_depth = threading.local()
_delegate_role = threading.local()
# Whether THIS thread currently holds ``llm_lock``. Sync ``delegate_task``
# runs inside a locked parent turn; the child must not re-acquire.
# Background workers run on a fresh thread and MUST acquire per turn so
# the main session can keep talking between worker batches.
_llm_lock_held = threading.local()


def _run_delegate_coroutine(coroutine: Any) -> Any:
    """Run an async delegate lifecycle from Jaeger's synchronous tool lane."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    # Tool calls normally run outside an event loop. Keep this safe for an
    # embedding host that invokes Jaeger from one: a private thread owns the
    # temporary loop instead of attempting nested ``run_until_complete``.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="delegate-runtime") as pool:
        return pool.submit(asyncio.run, coroutine).result()


def _delegate_external(
    runtime_id: str,
    task: str,
    *,
    required_capabilities: list[str] | None = None,
    sensitivity: str = "personal",
    estimated_cost_usd: float = 0.0,
) -> dict[str, Any]:
    """Dispatch one task through a registered external runtime.

    Registration is plugin-owned. This function supplies durable Jaeger
    commitment/run records and deliberately does not promote worker-proposed
    memory candidates.
    """
    import os
    import uuid
    from dataclasses import asdict
    from pathlib import Path

    from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
    from jaeger_agent.delegates import (
        DelegateExecutor,
        DelegateRequest,
        get_delegate_registry,
        register_builtin_delegates,
    )
    from jaeger_agent.delegates.routing import DelegateRouter

    register_builtin_delegates()
    registry = get_delegate_registry()
    try:
        estimated_cost = float(estimated_cost_usd)
        if estimated_cost < 0:
            raise ValueError("estimated_cost_usd cannot be negative")
    except (TypeError, ValueError) as exc:
        return {"delegated": False, "runtime": runtime_id, "error": str(exc)}
    if sensitivity not in {"public", "personal", "sensitive", "private", "secret"}:
        return {
            "delegated": False,
            "runtime": runtime_id,
            "error": f"unknown delegate sensitivity: {sensitivity}",
        }
    if runtime_id == "auto":
        try:
            route = _run_delegate_coroutine(
                DelegateRouter(registry).choose(
                    required_capabilities=frozenset(required_capabilities or ()),
                    sensitivity=sensitivity,
                )
            )
            runtime_id = route.runtime_id
        except Exception as exc:  # noqa: BLE001 - tool boundary
            return {
                "delegated": False,
                "runtime": "auto",
                "error": f"{type(exc).__name__}: {exc}",
            }
    elif registry.get(runtime_id) is None:
        return {
            "delegated": False,
            "error": f"unknown external delegate runtime: {runtime_id}",
            "available_runtimes": [item.runtime_id for item in registry.list()],
        }

    try:
        from jaeger_agent.core import workspace

        root = workspace.get_project_root()
        workspace_path = Path(root).resolve() if root else None
    except Exception:  # noqa: BLE001 - workspace is optional for delegates
        workspace_path = None

    cost_store = None
    layout = _main()._pipeline.get("layout")
    if layout is not None:
        from jaeger_ai.features.cost_tracking import CostStore

        cost_store = CostStore(layout.memory_dir / "costs.db")
        decision = cost_store.authorize(runtime_id, estimated_cost)
        if not decision.allowed:
            cost_store.close()
            return {
                "delegated": False,
                "runtime": runtime_id,
                "error": decision.reason,
                "budget": asdict(decision),
            }

    commitments = SqliteCommitmentStore()
    runs = SqliteRunStore()
    commitment = commitments.create(
        task,
        kind="delegation",
        payload={"runtime_id": runtime_id, "source": "delegate_task"},
    )
    commitments.transition(commitment.id, "active")
    run = runs.create(
        commitment.id,
        provider=runtime_id,
        owner_pid=os.getpid(),
        payload={"runtime_id": runtime_id, "prompt": task},
        relation="delegate",
    )

    request = DelegateRequest(
        task_id=run.id,
        prompt=task,
        workspace=workspace_path,
        required_capabilities=frozenset(required_capabilities or ()),
        sensitivity=sensitivity,  # validated by DelegateRequest
        idempotency_key=f"delegate:{commitment.id}:{uuid.uuid4().hex}",
    )
    try:
        result = _run_delegate_coroutine(
            DelegateExecutor(registry, runs).execute(runtime_id, request)
        )
    except Exception as exc:  # noqa: BLE001 - tool boundary returns structured failure
        if cost_store is not None:
            cost_store.close()
        try:
            commitments.transition(commitment.id, "blocked")
        except Exception:  # noqa: BLE001 - preserve the originating failure
            pass
        return {
            "delegated": False,
            "runtime": runtime_id,
            "task_id": run.id,
            "error": f"{type(exc).__name__}: {exc}",
        }

    if cost_store is not None:
        actual_cost = result.metadata.get("cost_usd", estimated_cost)
        if isinstance(actual_cost, (int, float)) and actual_cost > 0:
            cost_store.record(
                runtime_id=runtime_id,
                cost_usd=float(actual_cost),
                task_id=run.id,
            )
        cost_store.close()

    commitments.transition(
        commitment.id,
        "completed" if result.status == "completed" else "blocked",
    )
    payload = asdict(result)
    payload.update({
        "delegated": result.status == "completed",
        "runtime": runtime_id,
        "task_id": run.id,
        "commitment_id": commitment.id,
        "memory_candidates_trusted": False,
    })
    return payload


def _wt_result(info: dict[str, Any] | None) -> dict[str, Any]:
    """Surface a child's worktree outcome to the parent, or nothing.

    Returns ``{}`` when isolation was off or unavailable, so the delegate
    result shape is unchanged on the default path. When a worktree WAS used
    the parent needs the payload verbatim — it carries ``inspection_failed``
    and ``note`` in the case where git could not be probed, and the parent
    agent only ever sees this dict, so dropping it would turn "we could not
    tell whether the child produced work" into a silent "it produced none".
    """
    if not info:
        return {}
    result = info.get("result")
    return {"worktree": result} if result else {}


def _delegate_internal(client: Any, subtask: str) -> dict[str, Any]:
    """Run a subtask through the same agent loop with a fresh history.

    Same pattern python_pydantic_ai uses: bumps a thread-local depth
    counter, runs the subtask, returns the answer + elapsed time.
    Depth-limited to prevent runaway recursion if a sub-agent decides
    to delegate again.

    Role travels on ``_delegate_role`` (not a kwarg) so tests that
    monkeypatch this function with ``(client, task)`` keep working.
    ``leaf`` (Hermes default) seeds the child's depth at the cap so a
    nested ``delegate_task`` refuses immediately. ``orchestrator`` uses
    the normal +1 increment, bounded by ``_DELEGATE_MAX_DEPTH``.
    """
    from jaeger_ai.core.runtime.delegation import (
        ORCHESTRATOR, leaf_child_depth, normalize_role,
    )

    depth = getattr(_delegate_depth, "value", 0)
    if depth >= _DELEGATE_MAX_DEPTH:
        return {
            "delegated": False,
            "error": f"delegate recursion limit hit ({_DELEGATE_MAX_DEPTH}); "
                     "the sub-agent tried to delegate again — refusing.",
        }
    clean = (subtask or "").strip()
    if not clean:
        return {"delegated": False, "error": "empty subtask"}

    role_name = normalize_role(getattr(_delegate_role, "value", None))
    _delegate_depth.value = (
        depth + 1 if role_name == ORCHESTRATOR
        else leaf_child_depth(_DELEGATE_MAX_DEPTH)
    )
    started = time.perf_counter()

    # Opt-in git worktree isolation (ported from hermes-agent). Off unless
    # JAEGER_SUBAGENT_WORKTREE is set, and a no-op outside a git repo, so
    # the default path below is byte-for-byte what it was before.
    #
    # The context manager owns the whole child turn: it rebinds
    # ``workspace.get_project_root`` to the worktree for the duration (which
    # is what file/code tools resolve against), restores the parent's root on
    # the way out, and finalizes — pruning only a provably empty, clean tree.
    import uuid as _uuid

    # Mark this turn as a delegated child's. The kanban tools refuse board
    # mutations from children: a child shares the parent's process, so an
    # inherited JAEGER_KANBAN_TASK is not proof that IT owns the card.
    # ContextVar, so anything the child spawns inherits the mark too.
    from jaeger_agent.delegation_context import delegated_child as _child_ctx
    _child_stack = _child_ctx()
    from jaeger_agent import subagent_worktree as _wt
    _wt_stack = _wt.isolated_child(f"d{depth + 1}-{_uuid.uuid4().hex[:6]}")
    _child_entered = False
    _worktree_entered = False
    _wt_info: dict[str, Any] | None = None
    _delegate_out: dict[str, Any] | None = None
    iter_out: dict[str, Any] | None = None
    try:
        _child_stack.__enter__()
        _child_entered = True
        _wt_info = _wt_stack.__enter__()
        _worktree_entered = True
        if _wt_info is not None:
            # The child cannot infer it is sandboxed, so say so in its prompt.
            clean = f"{clean}{_wt_info['context_note']}"

        # Phase-6.2 cutover: delegate now drives the new JaegerAgent
        # loop. A fresh ``JaegerAgent`` per subtask keeps history scoped
        # to the delegate's work (a child agent doesn't inherit the
        # parent's context — the spec calls this out).
        from jaeger_agent.loop.runtime_bridge import build_jaeger_agent, drive_one_turn
        from jaeger_ai.core.runtime.agent_controller import JaegerAgentController
        from jaeger_ai.core.runtime.autonomous_runner import looks_like_batch
        from jaeger_ai.core.runtime.execution import max_steps as _max_steps
        from jaeger_ai.features.dispatcher.router import prepare_turn_text
        _cfg = _main()._pipeline.get("config")
        _ctx, _reserve = _main()._context_budget_for(_cfg)
        sub_agent = build_jaeger_agent(
            client,
            system_prompt=_main()._pipeline["system_prompt"],
            toolsets=_main()._pipeline.get("toolsets"),
            skip_final_tools=_main().SKIP_FINAL_TOOLS,
            ctx_window=_ctx,
            completion_reserve=_reserve,
        )
        lock = _main()._pipeline.get("llm_lock")
        parent_holds_lock = bool(getattr(_llm_lock_held, "value", False))

        def _drive(prompt: str) -> dict[str, Any]:
            prepared = prepare_turn_text(
                sub_agent, prompt, session_key="delegate", domain=False,
            )
            if lock is not None and not parent_holds_lock:
                with lock:
                    return drive_one_turn(sub_agent, prepared)
            return drive_one_turn(sub_agent, prepared)

        if looks_like_batch(clean):
            def _turn(_client: Any, user_text: str, *, session_key: str,
                      allow_persona: bool = True) -> dict[str, Any]:
                iter_out = _drive(user_text)
                return {
                    "text": str(iter_out.get("answer") or "").strip(),
                    "error": None,
                    "tool_activity": iter_out.get("tool_activity") or [],
                    "spoke_via_tool": False,
                    "elapsed_s": float(iter_out.get("elapsed_s") or 0.0),
                    "skipped_final": bool(iter_out.get("skipped")),
                }

            def _on_progress(info: dict[str, Any]) -> None:
                bus = _main()._pipeline.get("event_bus")
                if bus is None:
                    return
                from jaeger_ai.core.runtime.work_ledger import (
                    active_ledger, progress_event,
                )
                ledger = active_ledger()
                try:
                    bus.publish("tool.progress", **progress_event(
                        ledger,
                        state=str(info.get("state") or "RUNNING"),
                        step=info.get("step"),
                    ))
                except Exception:  # noqa: BLE001
                    pass

            packed = JaegerAgentController(
                client,
                max_steps=_max_steps(),
                turn_fn=_turn,
                isolated=True,
                batch=True,
                on_progress=_on_progress,
                allow_persona=False,
                agent=sub_agent,
            ).run_to_completion(clean, "delegate")
            worker = packed["output"]
            answer = worker.get("summary") or worker.get("text") or ""
            elapsed = time.perf_counter() - started
            _delegate_out = {
                "delegated": True,
                "subtask": clean,
                "answer": str(answer).strip(),
                "summary": str(worker.get("summary") or ""),
                "depth": depth + 1,
                "elapsed_s": round(elapsed, 3),
                "autonomous": True,
                "steps": int(worker.get("steps") or packed.get("steps") or 0),
                "halt_reason": worker.get("halt_reason") or packed.get("reason") or "",
                "state": packed.get("status"),
            }
        else:
            iter_out = _drive(clean)
    except Exception as exc:
        _delegate_out = {
            "delegated": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        _delegate_depth.value = depth
        # Restores the parent's project root and finalizes the worktree.
        if _worktree_entered:
            try:
                _wt_stack.__exit__(None, None, None)
            except Exception:  # noqa: BLE001 — isolation teardown is best-effort
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "delegate: worktree teardown failed", exc_info=True)
        if _child_entered:
            _child_stack.__exit__(None, None, None)

    # A context-manager ``__exit__`` runs after a return expression is
    # evaluated. Build the final payload only now so worktree finalization's
    # ``result`` entry is present for success, batch, and failure paths.
    if _delegate_out is not None:
        _delegate_out.update(_wt_result(_wt_info))
        return _delegate_out

    elapsed = time.perf_counter() - started
    # ``drive_one_turn`` returns a shape that includes ``answer``,
    # ``skipped``, ``tool_activity``, etc.  Translate to the legacy
    # ``iter_out`` keys the surrounding code below expects.
    # ``drive_one_turn`` already populates ``answer`` for both the
    # skip-final shortcut and the full loop path — no separate result
    # object to interrogate.
    assert iter_out is not None
    answer = iter_out.get("answer") or ""
    return {
        "delegated": True,
        "subtask": clean,
        "answer": str(answer).strip(),
        "depth": depth + 1,
        "elapsed_s": round(elapsed, 3),
        **_wt_result(_wt_info),
    }


# Concurrent-subagent cap, ASKED of the brain rather than assumed.
#
# This used to be the constant 2, justified by llama-cpp serializing
# decode — true of an in-process model, false of every server brain. A
# cloud endpoint takes eight concurrent requests without noticing, and
# hardcoding the local number meant swapping to a cloud brain kept the
# local brain's ceiling. See
# :mod:`jaeger_ai.core.models.brain_profile`: in-process stays at 1
# (a second caller only queues behind the decode lock), a local server
# gets 3, a hosted endpoint 8, and ``JAEGER_BRAIN_CONCURRENCY``
# overrides all of it.
#
# For sustained background work Deep Think is still the better
# mechanism than a wide fan-out, on any brain.
def _max_parallel_subagents() -> int:
    from jaeger_ai.core.models.brain_profile import active_profile

    return max(1, active_profile().max_subagents)


def _delegate_background(client: Any, subtasks: list[str], *, role: str = "leaf") -> dict[str, Any]:
    """Admit durable child tasks; never detach best-effort daemon threads."""
    from jaeger_agent.task_port import current_task_context
    context = current_task_context()
    clean = [s.strip() for s in (subtasks or []) if s and s.strip()]
    if not clean:
        return {"ok": False, "error": "no subtasks given"}
    parent_depth = int((context or {}).get('execution', {}).get('options', {}).get('delegation_depth', 0))
    if parent_depth >= _DELEGATE_MAX_DEPTH:
        return {"ok": False, "error": f"delegate recursion limit hit ({_DELEGATE_MAX_DEPTH})"}
    if context is None:
        return {"ok": False, "error": "Background delegation requires the Gateway execution owner"}
    inherited = dict(context)
    # The call was authorized under the parent's tool policy. Child effects
    # retain that workspace/model/tool scope and their own normal confirmations.
    inherited['source'] = 'client'
    execution = dict(context.get('execution') or {})
    execution['options'] = {**(execution.get('options') or {}), 'delegation_depth': parent_depth + 1}
    inherited['execution'] = execution
    handles = []
    for objective in clean:
        task = context['owner'].submit(objective, context=inherited,
            key=f"delegate:{context['request_id']}:{objective}")
        handles.append({'id':task['task_id'], 'task':objective, 'status':task['status']})
    return {'ok':True, 'background':True, 'dispatched':len(handles), 'handles':handles}


def _delegate_parallel(client: Any, subtasks: list[str], *, role: str = "leaf") -> dict[str, Any]:
    """Fan subtasks out across as many workers as the BRAIN supports.

    Width comes from :func:`_max_parallel_subagents`, which asks the
    live client (see :mod:`jaeger_ai.core.models.brain_profile`) instead
    of assuming the local one:

      * an in-process llama.cpp / MLX model runs ONE at a time — it
        cannot decode two prompts at once, so subagents serialize
        through ``_main()._pipeline['llm_lock']`` and the win is orchestration
        (queue N, collect all answers) plus overlap on non-LLM tool
        work, never decode speedup;
      * a server brain — LM Studio, Ollama, any hosted endpoint —
        interleaves requests properly, so the fan-out is a real
        wall-clock win and the width rises to match.

    More subtasks than the width is fine: the pool runs that many at a
    time and queues the rest. Returns one result entry per subtask, in
    input order, plus the width actually used."""
    from concurrent.futures import ThreadPoolExecutor

    clean = [s.strip() for s in (subtasks or []) if s and s.strip()]
    if not clean:
        return {"ok": False, "error": "no subtasks given"}

    parent_depth = getattr(_delegate_depth, "value", 0)
    if parent_depth >= _DELEGATE_MAX_DEPTH:
        return {
            "ok": False,
            "error": f"delegate recursion limit hit ({_DELEGATE_MAX_DEPTH})",
        }

    def _worker(task: str) -> dict[str, Any]:
        # Worker runs on a fresh thread — _delegate_depth is
        # thread-local, so seed it here to keep nested delegation
        # bounded.
        _delegate_depth.value = parent_depth + 1
        _delegate_role.value = role
        try:
            return _main()._delegate_internal(client, task)
        finally:
            _delegate_depth.value = parent_depth

    # The brain in front of us decides the width, not a constant.
    concurrency = min(_max_parallel_subagents(), len(clean))

    started = time.perf_counter()
    with ThreadPoolExecutor(
        max_workers=concurrency,
        thread_name_prefix="subagent",
    ) as pool:
        results = list(pool.map(_worker, clean))
    elapsed = time.perf_counter() - started

    succeeded = sum(1 for r in results if r.get("delegated"))
    return {
        "ok": True,
        "subtask_count": len(clean),
        "max_concurrent": concurrency,
        "succeeded": succeeded,
        "failed": len(clean) - succeeded,
        "results": results,
        "elapsed_s": round(elapsed, 3),
    }
