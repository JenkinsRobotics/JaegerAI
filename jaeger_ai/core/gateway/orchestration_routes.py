"""Extracted Gateway task-board & IDE orchestration routes mixin (Wave 10).

Owns `/v1/tasks*` and `/v1/orchestration/*` HTTP route handlers for
:class:`JaegerGatewayApp`.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)


class GatewayOrchestrationRoutesMixin:
    """Task-board and IDE orchestration route handlers for JaegerGatewayApp."""

    def _task_board_fields(self, body: dict[str, Any]) -> dict[str, Any]:
        """Validate the Tasks-board fields of a task submission (raises ValueError)."""
        out: dict[str, Any] = {}
        registry = None
        if body.get("agent_id"):
            registry = self._registry()
            agent_id = str(body["agent_id"]).strip()
            if registry.get_agent(agent_id) is None:
                raise ValueError(f"Unknown agent_id {agent_id!r}")
            out["agent_id"] = agent_id
        if body.get("eta"):
            from datetime import datetime
            eta = str(body["eta"]).strip()
            try:
                parsed = datetime.fromisoformat(eta)
            except ValueError as exc:
                raise ValueError("eta must be ISO 8601") from exc
            if parsed.tzinfo is None:
                raise ValueError("eta must carry a UTC offset")
            out["eta"] = eta
        if body.get("runner"):
            runner = str(body["runner"]).strip()
            if runner != "native":
                target = runner[len("delegate:"):] if runner.startswith("delegate:") else ""
                registry = registry or self._registry()
                if not target or registry.get_agent(target) is None:
                    raise ValueError("runner must be 'native' or 'delegate:<agent id>'")
            out["runner"] = runner
        return out

    async def handle_task_submission(self, request: web.Request) -> web.Response:
        session_id = str(request.query.get("session_id") or "")
        request_id = request.match_info["request_id"]
        if not session_id or self.store.get_session(session_id) is None:
            return web.json_response({"error": "Existing originating session required"}, status=404)
        return web.json_response({
            "session_id": session_id,
            "request_id": request_id,
            "tasks": [task.to_dict() for task in self.task_owner.store.client_submissions(session_id, request_id)],
        })

    async def handle_tasks(self, request: web.Request) -> web.Response:
        if request.method == "GET":
            from jaeger_ai.core.tasks.presentation import view
            tasks = [view(self, t) for t in self.task_owner.store.list_tasks()]
            for t in tasks:  # G5 join-on-read
                t["handoff_id"] = self.store.handoff_for_task(str(t.get("task_id") or t.get("id") or ""))
            agent_filter = request.query.get("agent_id")
            if agent_filter:
                tasks = [t for t in tasks if t.get("agent_id") == agent_filter]
            return web.json_response({"tasks": tasks})
        tier = self._current_tier()
        if tier == "plan":
            return web.json_response({"error": "Task submission is disabled in Plan mode"}, status=403)
        body = await request.json()
        parent = self.store.get_session(str(body.get("session_id") or ""))
        if parent is None:
            return web.json_response({"error": "Existing session_id required"}, status=400)
        execution = dict(body.get("execution") or {})
        execution.setdefault("workspace", parent.get("workspace") or "")
        execution["caller"] = request.get("caller_actor")
        try:
            submission_id = body.get("request_id")
            if submission_id is not None and (not isinstance(submission_id, str) or not submission_id.strip() or len(submission_id) > 128):
                raise ValueError("request_id must be nonempty text of at most128 characters")
            board = self._task_board_fields(body)
            board.setdefault("agent_id", self._session_agent_id(parent))
            result = self.task_owner.submit(
                str(body.get("goal") or ""),
                context={
                    "session_id": parent["session_id"],
                    "source": "client",
                    "execution": execution,
                    "request_id": submission_id,
                    "client_submission_id": submission_id,
                    **board,
                },
                artifacts=body.get("artifacts"),
                proposal=bool(body.get("proposal")),
            )
        except ValueError as exc:
            from jaeger_ai.core.tasks.store import TaskConflict
            return web.json_response({"error": str(exc)}, status=409 if isinstance(exc, TaskConflict) else 400)
        return web.json_response(
            {**result, "request_id": submission_id, "origin_session_id": parent["session_id"]},
            status=200 if result["replayed"] else 201,
        )

    async def handle_task(self, request: web.Request) -> web.Response:
        task = self.task_owner.store.get_task(request.match_info["id"])
        from jaeger_ai.core.tasks.presentation import view
        if not task:
            return web.json_response({"error": "Task not found"}, status=404)
        return web.json_response({**view(self, task), "handoff_id": self.store.handoff_for_task(request.match_info["id"])})

    async def handle_task_presentation(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.tasks.presentation import change
        try:
            receipt = change(self, request.match_info["id"], await request.json(), request["caller_actor"])
            return web.json_response(receipt, status=receipt["http_status"])
        except KeyError:
            return web.json_response({"error": "Task not found"}, status=404)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=409)

    async def handle_task_presentation_operation(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.tasks.presentation import operation
        try:
            return web.json_response(
                operation(self, request.match_info["id"], request.match_info["operation"], request["caller_actor"])
            )
        except KeyError:
            return web.json_response({"error": "Task presentation operation not found"}, status=404)

    async def handle_task_edit(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
            task = self.task_owner.edit_proposal(
                request.match_info["id"],
                goal=str(body.get("goal") or ""),
                expected_updated_at=float(body["expected_updated_at"]),
            )
            return web.json_response(task)
        except KeyError:
            return web.json_response({"error": "Task or version not found"}, status=404)
        except (TypeError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=409)

    async def handle_task_approve(self, request: web.Request) -> web.Response:
        task_id = request.match_info["id"]
        task = self.task_owner.store.get_task(task_id)
        if task is None:
            return web.json_response({"error": "Task not found"}, status=404)
        if task.is_terminal:
            return web.json_response({"error": "Terminal task cannot be approved", "task_id": task_id, "status": task.state.value}, status=409)
        if task.provenance.get("authorized"):
            return web.json_response({"task_id": task_id, "status": task.state.value})
        if request.can_read_body:
            body = await request.json()
            if "expected_updated_at" in body and body["expected_updated_at"] != task.updated_at:
                return web.json_response({"error": "Task changed; refresh before approving"}, status=409)
        self.task_owner.resolve(task_id, True)
        for approval in self.store.list_pending_approvals():
            if (approval.get("metadata") or {}).get("task_id") == task_id:
                self.store.resolve_approval(approval["approval_id"], approved=True, decision="once")
        current = self.task_owner.store.get_task(task_id)
        return web.json_response({"task_id": task_id, "status": current.state.value})

    async def handle_task_cancel(self, request: web.Request) -> web.Response:
        cancelled = await self.task_owner.cancel(request.match_info["id"])
        return web.json_response({"cancelled": cancelled}, status=200 if cancelled else 404)

    async def handle_list_orchestration_workers(self, request: web.Request) -> web.Response:
        """List registered IDE orchestration workers and their availability."""
        if self.orchestration is None:
            return web.json_response({"workers": []})
        workers = await self.orchestration.list_workers()
        return web.json_response({"workers": workers})

    async def handle_create_orchestration_task(self, request: web.Request) -> web.Response:
        """Validate and reserve a worker request before acknowledging admission."""
        tier = self._current_tier()
        if tier == "plan":
            return web.json_response({"error": "Orchestration tasks are disabled in Plan mode"}, status=403)
        if self.orchestration is None:
            return web.json_response({"error": "IDE orchestration service unavailable"}, status=503)

        from jaeger_ai.features.ide_orchestration.contracts import ParentTask, TaskBudget
        from jaeger_ai.features.ide_orchestration.service import (
            DuplicateSubmissionConflict,
            WorkerUnavailableError,
        )

        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise TypeError("Request body must be an object")
            for field in ("task_id", "goal", "worker"):
                if not isinstance(body.get(field), str) or not body[field].strip():
                    raise ValueError(f"{field} must be a nonempty string")
            task_id = body["task_id"].strip()
            key = body.get("idempotency_key", task_id)
            if not isinstance(key, str) or not key.strip():
                raise ValueError("idempotency_key must be a nonempty string")
            read_only = body.get("read_only", True)
            if not isinstance(read_only, bool):
                raise TypeError("read_only must be a boolean")
            if not read_only:
                return web.json_response(
                    {
                        "error": (
                            "Writable IDE orchestration requires a server-owned "
                            "authorization and verification plan"
                        )
                    },
                    status=403,
                )
            metadata = body.get("metadata", {})
            if not isinstance(metadata, dict):
                raise TypeError("metadata must be an object")
            capabilities = body.get("required_capabilities", [])
            if not isinstance(capabilities, list) or any(
                not isinstance(value, str) or not value.strip() for value in capabilities
            ):
                raise ValueError("required_capabilities must be a list of nonempty strings")
            workspace = body.get("workspace")
            if workspace is not None and (not isinstance(workspace, str) or not workspace):
                raise ValueError("workspace must be an absolute path or null")
            budget_raw = body.get("budget", {})
            if not isinstance(budget_raw, dict):
                raise TypeError("budget must be an object")
            for field in ("max_seconds", "max_cost_usd"):
                value = budget_raw.get(field, 300.0 if field == "max_seconds" else 0.0)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise TypeError(f"{field} must be numeric")
            turns = budget_raw.get("max_turns", 1)
            if isinstance(turns, bool) or not isinstance(turns, int):
                raise TypeError("max_turns must be an integer")
            parent_task = ParentTask(
                task_id=task_id,
                goal=body["goal"].strip(),
                assigned_worker=body["worker"].strip(),
                idempotency_key=key.strip(),
                workspace=Path(workspace) if workspace is not None else None,
                read_only=read_only,
                budget=TaskBudget(
                    max_seconds=float(budget_raw.get("max_seconds", 300.0)),
                    max_turns=turns,
                    max_cost_usd=float(budget_raw.get("max_cost_usd", 0.0)),
                ),
                metadata=metadata,
                required_capabilities=frozenset(capabilities),
            )
            raw_artifacts = body.get("artifacts") or []
            if not isinstance(raw_artifacts, list) or any(not isinstance(a, str) or not a.strip() for a in raw_artifacts):
                raise TypeError("artifacts must be a list of nonempty strings")
            self.task_owner.artifact_paths(str(workspace or ""), raw_artifacts)
            operation, replayed = self.orchestration.admit_parent_task(parent_task)
        except DuplicateSubmissionConflict as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except WorkerUnavailableError as exc:
            return web.json_response({"error": str(exc)}, status=404)
        except (ValueError, TypeError, OverflowError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

        if not replayed:
            operation_key = ("orchestration", task_id)
            self._running_tasks[operation_key] = operation

            def completed(done: asyncio.Task) -> None:
                if self._running_tasks.get(operation_key) is done:
                    self._running_tasks.pop(operation_key, None)
                if not done.cancelled() and done.exception() is not None:
                    logger.error("Orchestration task %s failed: %s", task_id, done.exception())

            operation.add_done_callback(completed)
            try:
                self.task_owner.open_dispatch(
                    orchestration_id=task_id, goal=body["goal"].strip(), worker=body["worker"].strip(),
                    workspace=str(workspace or ""), artifacts=raw_artifacts,
                    session_id=str(body.get("session_id") or ""),
                )
                self.orchestration_bridge.record_task_dispatch(
                    sender="gateway",
                    recipient=body["worker"].strip(),
                    task_id=task_id,
                    payload={"goal": body["goal"].strip(), "read_only": read_only, "workspace": str(workspace or "")},
                )
                operation.add_done_callback(lambda done, oid=task_id: self._settle_dispatch(oid, done))
            except Exception:
                logger.exception("could not open a task card for orchestration task %s", task_id)
        return web.json_response(
            self.orchestration.get_task(task_id), status=200 if replayed else 201,
        )

    async def handle_get_orchestration_task(self, request: web.Request) -> web.Response:
        """Get the current process-local worker task, progress and result."""
        if self.orchestration is None:
            return web.json_response({"error": "IDE orchestration service unavailable"}, status=503)
        task_id = request.match_info["id"]
        task = self.orchestration.get_task(task_id)
        if task is None:
            return web.json_response({"error": f"Task {task_id} not found"}, status=404)
        card = self.task_owner.store.get_task(f"orch:{task_id}")
        return web.json_response({
            **task,
            "task_state": card.state.value if card else None,
            "task_id_owner": card.task_id if card else None,
        })

    async def handle_cancel_orchestration_task(self, request: web.Request) -> web.Response:
        """Cancel an in-flight orchestration task."""
        if self.orchestration is None:
            return web.json_response({"error": "IDE orchestration service unavailable"}, status=503)
        task_id = request.match_info["id"]
        cancelled = await self.orchestration.cancel_task(task_id)
        return web.json_response({"cancelled": cancelled, "task_id": task_id})

    async def handle_follow_up_orchestration_task(self, request: web.Request) -> web.Response:
        """Continue a completed worker task in its existing conversation."""
        if self.orchestration is None:
            return web.json_response({"error": "IDE orchestration service unavailable"}, status=503)
        from jaeger_ai.features.ide_orchestration.contracts import ParentTask, TaskBudget
        from jaeger_ai.features.ide_orchestration.service import (
            DuplicateSubmissionConflict,
            WorkerUnavailableError,
        )
        parent_id = request.match_info["id"]
        parent = self.orchestration.get_task(parent_id)
        if parent is None:
            return web.json_response({"error": f"Task {parent_id} not found"}, status=404)
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("task_id"), str):
                raise ValueError("task_id must be a nonempty string")
            goal = body.get("goal")
            if not isinstance(goal, str) or not goal.strip():
                raise ValueError("goal must be a nonempty string")
            task_id = body["task_id"].strip()
            key = body.get("idempotency_key", task_id)
            if not isinstance(key, str) or not key.strip():
                raise ValueError("idempotency_key must be a nonempty string")
            task = ParentTask(
                task_id=task_id,
                goal=goal.strip(),
                assigned_worker=str(parent["worker"]),
                idempotency_key=key.strip(),
                read_only=bool(parent.get("read_only", True)),
                budget=TaskBudget(max_seconds=float(body.get("max_seconds", 300.0))),
                metadata={"parent_task_id": parent_id},
            )
            operation, replayed = self.orchestration.admit_follow_up(parent_id, task)
        except DuplicateSubmissionConflict as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except WorkerUnavailableError as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except (ValueError, TypeError, OverflowError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        if not replayed:
            operation_key = ("orchestration", task_id)
            self._running_tasks[operation_key] = operation
            operation.add_done_callback(
                lambda done: self._running_tasks.pop(operation_key, None)
                if self._running_tasks.get(operation_key) is done else None
            )
            try:
                self.task_owner.open_dispatch(
                    orchestration_id=task_id, goal=goal.strip(), worker=str(parent["worker"]),
                    session_id=str(body.get("session_id") or ""),
                )
                operation.add_done_callback(lambda done, oid=task_id: self._settle_dispatch(oid, done))
            except Exception:
                logger.exception("could not open a task card for follow-up task %s", task_id)
        return web.json_response(
            self.orchestration.get_task(task_id), status=200 if replayed else 201,
        )
