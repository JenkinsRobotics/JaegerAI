"""Extracted Gateway turn streaming callbacks & owner ReAct loop mixin (Wave 2).

Streams durable ``turn.delta``, ``turn.reasoning``, and redacted ``tool.*``
events onto the Gateway event bus and runs the owner's continued ReAct turn.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any, Callable

from jaeger_ai.contract.model_ids import split_routed_model_id

logger = logging.getLogger(__name__)

OWNER_RUN_SESSION_PREFIX = "owner:"


def _server_attr(name: str) -> Any:
    from . import server as _server
    return getattr(_server, name)


def _live_activity_id(*args: Any, **kwargs: Any) -> Any:
    return _server_attr("_live_activity_id")(*args, **kwargs)


def _safe_tool_duration(*args: Any, **kwargs: Any) -> Any:
    return _server_attr("_safe_tool_duration")(*args, **kwargs)


def _safe_tool_event_name(*args: Any, **kwargs: Any) -> Any:
    return _server_attr("_safe_tool_event_name")(*args, **kwargs)


def _tool_event_args(*args: Any, **kwargs: Any) -> Any:
    return _server_attr("_tool_event_args")(*args, **kwargs)


def _tool_input_text(*args: Any, **kwargs: Any) -> Any:
    return _server_attr("_tool_input_text")(*args, **kwargs)


def _tool_output_text(*args: Any, **kwargs: Any) -> Any:
    return _server_attr("_tool_output_text")(*args, **kwargs)


def _tool_public_message(*args: Any, **kwargs: Any) -> Any:
    return _server_attr("_tool_public_message")(*args, **kwargs)


def _tool_sources(*args: Any, **kwargs: Any) -> Any:
    return _server_attr("_tool_sources")(*args, **kwargs)


def _GatewayToolConfirmationProvider(*args: Any, **kwargs: Any) -> Any:
    return _server_attr("_GatewayToolConfirmationProvider")(*args, **kwargs)


def _GatewayLocalReadAccessProvider(*args: Any, **kwargs: Any) -> Any:
    return _server_attr("_GatewayLocalReadAccessProvider")(*args, **kwargs)


def _GatewayLocalWriteAccessProvider(*args: Any, **kwargs: Any) -> Any:
    return _server_attr("_GatewayLocalWriteAccessProvider")(*args, **kwargs)


class GatewayTurnCallbacksMixin:
    """Turn-streaming callbacks and owner ReAct execution methods for JaegerGatewayApp."""

    def _turn_stream_callbacks(self, session_id: str, request_id: str, *, model: str | None = None,
                               lane: str | None = None,
                               on_model_identity: Callable[[str | None], None] | None = None,
                               ) -> tuple[Any, Callable[[], None]]:
        """Agent callbacks that stream this turn to clients as durable events.

        ``turn.delta`` carries answer text (what Swift's voice loop and the
        bridge speak/render incrementally); ``turn.reasoning`` carries model
        deliberation, never part of the answer. Tool lifecycle events contain
        a catalog-shaped name, phase, outcome, bounded duration and, on start,
        redacted and bounded arguments (``_tool_event_args``: no credentials,
        no payload bodies). Results and errors never enter the client stream.
        Deltas are batched — each publish is a durable row — and are flushed
        before reasoning/tool boundaries and the terminal event so replay
        reproduces the exact observed order.
        """
        from jaeger_agent.loop.callbacks import AgentCallbacks

        timing = self._turn_timings.get(request_id)
        row = self.store.get_request(request_id) or {}
        ids = {"turn_id": row.get("turn_id") or request_id, "request_id": request_id}
        lock = threading.Lock()
        pending: list[str] = []
        text_item: list[str | None] = [None]
        last = [time.monotonic()]
        # The loop publishes the model's real tool-call id on a ContextVar
        # (jaeger_agent.live); the activity id is derived from it so delegates,
        # hooks and progress land on the same span. A FIFO per raw name remains
        # only as the fallback for callers that do not set it.
        active_tools: dict[str, list[str]] = {}

        heartbeats: dict[str, threading.Event] = {}
        cb_holder: list[Any] = [None]

        def heartbeat(activity_id: str, tool: str) -> None:
            # A long tool is not silent: every _server_attr('TOOL_HEARTBEAT_S') the span gets a
            # tool.progress tick (elapsed time) until it finishes or the turn ends.
            stop = heartbeats[activity_id]
            t0 = time.monotonic()
            step_at_start = step_ref()
            while not stop.wait(_server_attr('TOOL_HEARTBEAT_S')):
                elapsed = time.monotonic() - t0
                try:
                    status = (self.store.get_request(request_id) or {}).get("status")
                    if elapsed > 3600 or (status and status not in {
                            "running", "approved", "admitted", "cancelling", "queued"}):
                        break
                    self.event_bus.publish(session_id, "tool.progress", {
                        **ids, **step_at_start, "call_id": activity_id, "activity_id": activity_id, "tool": tool,
                        "heartbeat": True, "elapsed_s": round(elapsed, 1),
                        "message": f"still running · {int(elapsed)} s"})
                except Exception:  # noqa: BLE001 — a store going away ends the heartbeat
                    break
            heartbeats.pop(activity_id, None)

        def live_activity() -> str | None:
            from jaeger_events import live as _live
            call = _live.current_tool_call()
            return _live_activity_id(request_id, call) if call else None
        file_snapshots: dict[str, list[dict]] = {}
        # One model call = one step span (contract/trace.py). Text/reasoning
        # carry the step that produced them; tools carry the step that asked.
        step: dict[str, Any] = {"id": None, "index": 0, "t0": None}

        def step_ref() -> dict[str, Any]:
            return {"step_id": step["id"]} if step["id"] else {}

        def flush() -> None:
            with lock:
                text = "".join(pending)
                pending.clear()
                last[0] = time.monotonic()
            if text:
                if text_item[0] is None:
                    text_item[0] = f"text_{uuid.uuid4().hex}"
                self.event_bus.publish(session_id, "turn.delta", {
                    **ids, **step_ref(), "delta": text, "channel": "provisional",
                    "content_type": "provisional", "item_id": text_item[0],
                })

        reasoning_started: list[float | None] = [None]
        # Reasoning arrives a few characters at a time; like text deltas it is
        # coalesced (~_server_attr('TURN_DELTA_BATCH_S')) and always flushed before any other
        # event, so ordering is unchanged.
        reasoning_pending: list[str] = []
        reasoning_last = [time.monotonic()]

        def flush_reasoning() -> None:
            with lock:
                text = "".join(reasoning_pending)
                reasoning_pending.clear()
                reasoning_last[0] = time.monotonic()
            if text:
                self.event_bus.publish(session_id, "turn.reasoning", {**ids, **step_ref(), "text": text})

        def end_reasoning() -> None:
            # One ``turn.reasoning.done`` per reasoning run, when the answer,
            # a tool, or the end of the turn follows it (chat "Thought for Ns").
            flush_reasoning()
            with lock:
                started, reasoning_started[0] = reasoning_started[0], None
            if started is not None:
                self.event_bus.publish(session_id, "turn.reasoning.done", {
                    **ids, **step_ref(), "started_at": started,
                    "duration_ms": max(0, int((time.time() - started) * 1000))})

        def on_delta(piece: str) -> None:
            if timing is not None and piece:
                timing.first_token()
            end_reasoning()
            with lock:
                pending.append(str(piece))
                due = sum(map(len, pending)) >= _server_attr('TURN_DELTA_BATCH_CHARS') or (
                    time.monotonic() - last[0] >= _server_attr('TURN_DELTA_BATCH_S'))
            if due:
                flush()

        def on_reasoning(text: str) -> None:
            flush()
            # Reasoning is a separate stream. Only a new model call or
            # tool boundary starts a new assistant text item.
            if text:
                with lock:
                    if reasoning_started[0] is None:
                        reasoning_started[0] = time.time()
                    reasoning_pending.append(str(text))
                    due = sum(map(len, reasoning_pending)) >= _server_attr('TURN_REASONING_BATCH_CHARS') or (
                        time.monotonic() - reasoning_last[0] >= _server_attr('TURN_DELTA_BATCH_S'))
                if due:
                    flush_reasoning()

        def on_tool_progress(name: str, phase: str, data: Any) -> None:
            # ``done`` is followed immediately by the richer ``tool_done``
            # callback, which knows success/failure. Publishing here would
            # create two terminal rows for one call.
            if phase != "start":
                return
            flush()
            end_reasoning()
            raw_name = str(name or "")
            activity_id = live_activity() or f"tool_{uuid.uuid4().hex}"
            if timing is not None:
                timing.tool_start(_safe_tool_event_name(name))
            self.event_bus.publish(session_id, "turn.progress", {
                **ids, "channel": "commentary", "content_type": "commentary",
                "activity_id": activity_id, "message": _tool_public_message(name, data),
            })
            text_item[0] = None
            with lock:
                active_tools.setdefault(raw_name, []).append(activity_id)
            if raw_name in {"write_file", "append_file", "patch", "delete_file", "move_file", "copy_file"} and isinstance(data, dict):
                try:
                    from jaeger_agent.core.workspace import _resolve_write
                    keys = ["src", "dst"] if raw_name == "move_file" else ["dst"] if raw_name == "copy_file" else ["path"]
                    file_snapshots[activity_id] = [self.file_changes.begin(_resolve_write(str(data[key]))) for key in keys]
                except Exception:
                    logger.debug("File change checkpoint unavailable for %s", raw_name)
            self._active_tool_call[request_id] = activity_id
            if _server_attr('TOOL_HEARTBEAT_S') > 0:
                heartbeats[activity_id] = threading.Event()
                threading.Thread(target=heartbeat, args=(activity_id, _safe_tool_event_name(name)),
                                 name="tool-heartbeat", daemon=True).start()
            self.event_bus.publish(session_id, "tool.started", {
                **ids, **step_ref(),
                "session_id": session_id,
                "activity_id": activity_id,
                "call_id": activity_id,
                "tool": _safe_tool_event_name(name),
                "phase": "started",
                "success": None,
                "ok": None,
                "text": "Started",
                **({"input": shown} if (shown := _tool_input_text(raw_name, data)) else {}),
                "args": _tool_event_args(data),
            })

        def on_tool_done(
            name: str,
            args: dict[str, Any],
            result: Any,
            ok: bool,
            error: str | None,
            elapsed_s: float,
        ) -> None:
            # Arguments, result and error are intentionally not published. They
            # can contain credentials, file contents, prompts, or command output.
            # The one exception is ``update_plan``: its result is the plan the
            # model chose to show the operator, and only that validated payload
            # (steps, statuses, an optional note) leaves this callback.
            self._request_tools.setdefault(request_id, []).append(str(name or ""))
            output_text = _tool_output_text(str(name or ""), result)
            needs_permission = isinstance(result, dict) and result.get("needs_permission") is True
            sources = _tool_sources(result) if ok else []
            attachment = None
            if ok:
                try:
                    from jaeger_ai.core.gateway.generated_media import register_generated_image
                    attachment = register_generated_image(
                        self, session_id=session_id, request_id=request_id,
                        tool_name=str(name or ""), result=result,
                    )
                except Exception:
                    logger.warning("Generated image could not be attached to the session", exc_info=True)
            if ok and attachment is None and str(name or "") == "share_file":
                # share_file registered the attachment; surface it as the same
                # persisted chat part a generated image uses (parity P14).
                shared = result
                if isinstance(shared, str):
                    try:
                        shared = json.loads(shared)
                    except ValueError:
                        shared = None
                if isinstance(shared, dict) and shared.get("ok") and shared.get("attachment_id"):
                    attachment = {"attachment_id": str(shared["attachment_id"]), "name": shared.get("name"),
                                  "mime": shared.get("mime"), "size": shared.get("size_bytes"),
                                  "sha256": shared.get("sha256")}
                    if not output_text:
                        output_text = f"Shared {shared.get('name') or 'file'}"
            if attachment and not output_text:
                output_text = f"Generated {attachment.get('name') or 'image'}"
            plan_payload = None
            if str(name or "") == "update_plan" and ok and isinstance(result, dict) and result.get("ok"):
                plan_payload = {
                    "plan": [
                        {"step": str(item.get("step", ""))[:500], "status": str(item.get("status", ""))}
                        for item in (result.get("plan") or []) if isinstance(item, dict)
                    ][:50],
                    "summary": dict(result.get("summary") or {}),
                }
                if isinstance(result.get("explanation"), str):
                    plan_payload["explanation"] = result["explanation"][:500]
            from jaeger_ai.contract.tool_outcomes import tool_outcome
            outcome = tool_outcome(bool(ok), result)
            succeeded = bool(ok)
            public_summary = _tool_public_message(name, args, finished=True, ok=succeeded)
            del args, result, error
            flush()
            end_reasoning()
            raw_name = str(name or "")
            if timing is not None:
                timing.tool_done(_safe_tool_event_name(name))
            real = live_activity()
            with lock:
                queued = active_tools.get(raw_name)
                if real and queued and real in queued:
                    queued.remove(real)
                    activity_id = real
                else:
                    activity_id = queued.pop(0) if queued else (real or f"tool_{uuid.uuid4().hex}")
                if queued == []:
                    active_tools.pop(raw_name, None)
            beat = heartbeats.get(activity_id)
            if beat is not None:
                beat.set()
            snapshots = file_snapshots.pop(activity_id, [])
            if snapshots:
                try:
                    for snapshot in snapshots:
                        self.file_changes.finish(session_id, request_id, snapshot)
                    self.event_bus.publish(session_id, "files.changed", {
                        **ids, **self.file_changes.describe(session_id, request_id)})
                except (OSError, ValueError, UnicodeError):
                    logger.warning("File change checkpoint could not settle for %s", raw_name)
            duration = _safe_tool_duration(elapsed_s)
            phase = "completed" if succeeded else "failed"
            detail = public_summary
            if self._active_tool_call.get(request_id) == activity_id:
                self._active_tool_call.pop(request_id, None)
            self.event_bus.publish(session_id, f"tool.{phase}", {
                **ids, **step_ref(),
                "session_id": session_id,
                "activity_id": activity_id,
                "call_id": activity_id,
                "tool": _safe_tool_event_name(name),
                "phase": phase,
                "outcome": outcome,
                "success": succeeded,
                "ok": succeeded,
                "elapsed_s": duration,
                "text": detail,
                "summary": detail,
                **({"output": output_text} if output_text else {}),
                # A flag, not the result: says the tool was blocked by a missing
                # OS permission (e.g. macOS Accessibility) so the cause is visible.
                **({"needs_permission": True} if needs_permission else {}),
            })
            if sources:
                self.event_bus.publish(session_id, "sources", {**ids, "sources": sources})
            if attachment:
                self.event_bus.publish(session_id, "turn.attachment", {
                    **ids, **step_ref(),
                    "attachment_id": attachment["attachment_id"],
                    "name": attachment.get("name"),
                    "mime": attachment.get("mime"),
                    "size": attachment.get("size"),
                    "sha256": attachment.get("sha256"),
                    "tool": _safe_tool_event_name(name),
                })
            if plan_payload is not None:
                self.event_bus.publish(session_id, "turn.plan", {**ids, **plan_payload})

        def finish() -> None:
            flush()
            end_reasoning()

        def on_thinking(message: str) -> None:
            # Loop status (retry, context compaction, waiting), not invented
            # model reasoning. Preserve chronological boundaries in the feed.
            flush()
            end_reasoning()
            self.event_bus.publish(session_id, "turn.progress", {
                **ids, "channel": "status", "content_type": "status",
                "message": str(message)[:2000],
            })

        def on_model_start() -> None:
            if timing is not None:
                timing.model_start()
            flush()
            end_reasoning()
            text_item[0] = None
            step["index"] += 1
            step["id"] = f"{request_id}:{step['index']}"
            step["t0"] = time.monotonic()
            ident = getattr(cb_holder[0], "model_identity", None) if cb_holder else None
            ident = {k: str(v)[:120] for k, v in (ident or {}).items() if isinstance(v, str) and v}
            self.event_bus.publish(session_id, "model.started", {
                **ids, "step_id": step["id"], "index": step["index"], **ident,
                "model": ident.get("model") or model
                or str((self.store.get_request(request_id) or {}).get("model") or "") or None,
                "lane": lane or None,
            })

        def on_model_done(usage: dict[str, int]) -> None:
            if timing is not None:
                timing.model_done(usage)
            flush()
            end_reasoning()
            if step["id"] is None:
                return
            ok = not (isinstance(usage, dict) and usage.get("failed"))
            usage = usage if isinstance(usage, dict) else {}
            tokens = {k: int(v) for k, v in usage.items()
                      if k in {"prompt_tokens", "completion_tokens"} and isinstance(v, int)}
            # A lane that does not report usage (e.g. a CLI brain) says so
            # rather than showing zeros as if they were measured.
            reported = any(tokens.values())
            identity = {k: str(usage[k])[:120] for k in ("model", "provider", "actual_model", "error")
                        if isinstance(usage.get(k), str) and usage.get(k)}
            if ok and on_model_identity is not None:
                # The last successful response owns the answer's model identity.
                # Missing provider identity clears an earlier response's value;
                # a configured route is never substituted for observation.
                on_model_identity(identity.get("actual_model"))
            self.event_bus.publish(session_id, "model.finished", {
                **ids, "step_id": step["id"], "index": step["index"], "ok": ok,
                "usage": tokens if reported else {}, "usage_reported": reported,
                **({"cost_usd": round(float(usage["cost_usd"]), 6)}
                   if isinstance(usage.get("cost_usd"), (int, float)) and not isinstance(usage.get("cost_usd"), bool) else {}),
                **identity, **({"model": model} if model and "model" not in identity else {}),
                "lane": lane or None,
                "duration_ms": int((time.monotonic() - (step["t0"] or time.monotonic())) * 1000),
            })

        def on_model_input(outline: dict[str, Any]) -> None:
            self.event_bus.publish(session_id, "turn.context", {
                **ids, "outline": outline,
            })

        cb_holder[0] = AgentCallbacks(
            model_input=on_model_input,
            thinking=on_thinking,
            tool_selection=lambda receipt: self.event_bus.publish(session_id, "tools.selected", {**ids, "receipt": receipt}),
            model_call_start=on_model_start,
            model_call_done=on_model_done,
            stream_delta=on_delta,
            reasoning=on_reasoning,
            tool_progress=on_tool_progress,
            tool_done=on_tool_done,
        )
        return cb_holder[0], finish

    def _owner_react_turn(
        self, prompt: str, *, session_key: str, request_id: str,
        on_model: Callable[[str], None] | None = None,
        on_model_identity: Callable[[str | None], None] | None = None,
        execution: dict[str, Any] | None = None,
        continuation_state: dict[str, Any] | None = None,
        context_references: tuple[Any, ...] = (),
        prompt_mode: str = "agent",
    ) -> dict[str, Any]:
        """Run one inner ReAct step in the EntityRuntime OWNER process."""
        from jaeger_ai.core.entity.runtime import EntityRuntime

        runtime = EntityRuntime.get_singleton()
        native = None
        try:
            row = self.store.get_request(request_id)
            native = str((row or {}).get("native_run_id") or "") or None
        except Exception:
            pass
        if execution is not None:
            # Admitted request: execute exactly what was frozen at admission.
            selection = execution
            lane, selected_model = split_routed_model_id(str(execution.get("model") or ""))
        else:
            # Pre-snapshot (digest v1) request recovered after upgrade.
            session = self.store.get_session(session_key) or {}
            selection = session.get("metadata") or {}
            lane, selected_model = split_routed_model_id(str(selection.get("model") or session.get("model") or ""))
        callbacks, flush = self._turn_stream_callbacks(session_key, request_id,
                                                       model=selected_model or None, lane=lane or None,
                                                       on_model_identity=on_model_identity)
        callbacks.context_references = context_references
        agent_safety_turn = [False]
        from jaeger_agent.tool_executor import tool_allowlist
        from jaeger_agent.core.workspace import read_confinement

        grant = execution.get("allowed_tools") if execution is not None else None
        try:
            # The admitted tool grant scopes the agent built for this turn
            # ([] = no tools; absent = the owner's normal catalog).
            # Agent mode works in a session worktree (git) and is checkpointed
            # per turn, so its file changes can be applied, discarded or undone.
            safe_selection = selection
            from jaeger_ai.contract.modes import normalize_interaction_tier as _tier_of
            if _tier_of(selection.get("interaction_tier") or self._current_tier()) == "agent":
                try:
                    safe = self.agent_safety.prepare(session_key, request_id, str(selection.get("workspace") or "") or None)
                except Exception:  # noqa: BLE001 — safety setup never blocks the turn
                    logger.warning("agent safety unavailable for %s", request_id, exc_info=True)
                    safe = {}
                if safe.get("root"):
                    safe_selection = {**selection, "workspace": safe["root"]}
                    agent_safety_turn[0] = True
            from jaeger_agent.task_port import task_scope
            from jaeger_agent.core.workspace import write_authority
            request_row = self.store.get_request(request_id) or {}
            options = selection.get("options") or {}
            source = "background" if options.get("background") else "user"
            from jaeger_ai.main import interaction_request_sink
            from jaeger_events import live as _live
            live_ids = {"turn_id": request_row.get("turn_id") or request_id, "request_id": request_id}

            def _live_emit(name: str, data: dict[str, Any]) -> None:
                call = str(data.get("call_id") or "")
                if call and not call.startswith("sub_"):  # child-agent calls keep their own ids
                    data = {**data, "call_id": _live_activity_id(request_id, call)}
                self.event_bus.publish(session_key, name, {**live_ids, **data})

            with _live.bind(_live_emit), task_scope(self.task_owner, session_id=session_key, request_id=request_id,
                            execution=selection, user_text=request_row.get("input_text", prompt), source=source), \
                    interaction_request_sink(self._clarify_sink(session_key, request_id)), \
                    tool_allowlist(list(grant) if grant is not None else None), \
                    read_confinement(
                        self._read_roots(runtime, safe_selection, self._staged_upload_dir(session_key)),
                        request_access=_GatewayLocalReadAccessProvider(self, session_key, request_id),
                    ), write_authority(
                        request_access=_GatewayLocalWriteAccessProvider(self, session_key, request_id),
                    ):
                _live.emit("route.selected", {
                    "model": selected_model or None, "lane": lane or None,
                    "provider": str(selection.get("provider") or lane or "") or None,
                    "reason": "admitted request snapshot" if execution is not None else "session default (recovered request)",
                    "local_only": bool(options.get("local_only")),
                    "tools": "none" if grant == [] else ("granted subset" if grant is not None else "owner catalog"),
                })
                if continuation_state is not None:
                    passes = int(continuation_state.get("live_passes") or 0) + 1
                    continuation_state["live_passes"] = passes
                    if passes > 1:
                        _live.emit("loop.continuation", {
                            "pass": passes,
                            "reason": "owner continuation: the turn's objective was not closed by the last inner loop",
                        })
                _react_kw: dict[str, Any] = {}
                try:
                    if options.get("max_tool_calls") is not None:
                        _react_kw["max_tool_calls"] = max(1, int(options["max_tool_calls"]))
                except (TypeError, ValueError):
                    pass
                try:
                    if options.get("max_iterations") is not None:
                        _react_kw["max_iterations"] = max(1, int(options["max_iterations"]))
                except (TypeError, ValueError):
                    pass
                if options.get("finalize_after_first_tools"):
                    _react_kw["finalize_after_first_tools"] = True
                    from jaeger_ai.core.runtime.cron_turns import HEARTBEAT_FINALIZE_PROMPT
                    _react_kw["finalize_prompt"] = HEARTBEAT_FINALIZE_PROMPT
                outcome = runtime.run_subordinate_react(
                    prompt,
                    session_key=session_key,
                    request_id=request_id,
                    callbacks=callbacks,
                    continuation_state=continuation_state,
                    project_root=str(safe_selection.get("workspace") or "") or None,
                    confirmation_provider=_GatewayToolConfirmationProvider(self, session_key, request_id),
                    native_run_id=native,
                    model=selected_model or None,
                    provider=str(selection.get("provider") or lane or "") or None,
                    local_only=bool(options.get("local_only")),
                    attachments=self._turn_attachments(session_key, execution),
                    prompt_mode=prompt_mode,
                    **_react_kw,
                    on_model=on_model,
                    on_agent=lambda agent: self._active_agents.__setitem__(request_id, agent),
                    cancellation=self._cancellations.get(request_id),
                    on_run=lambda run_id: self.store.bind_native(
                        request_id,
                        native_run_id=run_id,
                        native_session=f"{OWNER_RUN_SESSION_PREFIX}{session_key}",
                    ),
                )
                halt = (outcome or {}).get("halt_reason") if isinstance(outcome, dict) else None
                _live.emit("loop.stop", {
                    "reason": str(halt) if halt else "final_answer",
                    "iterations": (outcome or {}).get("iterations") if isinstance(outcome, dict) else None,
                    "ok": not halt or str(halt) in {"final_answer", "skip_final"},
                })
                return outcome
        finally:
            flush()
            if agent_safety_turn[0] and not self._cancellations.is_cancelled(request_id):
                try:
                    turn = self.agent_safety.settle(session_key, request_id)
                    if turn.get("files"):
                        self.event_bus.publish(session_key, "files.changed", {
                            "request_id": request_id, **self.agent_safety.describe(session_key, request_id)})
                except Exception:  # noqa: BLE001
                    logger.warning("agent safety settle failed for %s", request_id, exc_info=True)

    def _continued_owner_react(
        self, prompt: str, *, session_key: str, request_id: str,
        on_model: Callable[[str], None] | None = None,
        on_model_identity: Callable[[str | None], None] | None = None,
        execution: dict[str, Any] | None = None,
        objective: str = "",
        context_references: tuple[Any, ...] = (),
    ) -> dict[str, Any]:
        """One admitted request: inner ReAct plus owner-side continuation."""
        from jaeger_ai.core.runtime.autonomous_runner import run_continued_turn

        continuation_state: dict[str, Any] = {}
        timing = self._turn_timings.get(request_id)

        def step(inner_prompt: str) -> dict[str, Any]:
            if timing is not None:
                timing.continuation()
            before = len(self._request_tools.get(request_id, []))
            out = self._owner_react_turn(
                inner_prompt, session_key=session_key, request_id=request_id,
                on_model=on_model, execution=execution,
                on_model_identity=on_model_identity,
                continuation_state=continuation_state,
                context_references=context_references,
                prompt_mode=("lean" if is_routine_lookup_turn(objective or prompt)
                             and not _options.get("task_id") else "agent"),
            )
            return {
                **out,
                "text": out.get("text") or "",
                "halt_reason": out.get("halt_reason"),
                "status": out.get("status") or ("failed" if out.get("error") else "completed"),
                "tools_used": list(self._request_tools.get(request_id, [])[before:]),
            }

        from jaeger_ai.core.runtime.work_ledger import ledger_scope, last_completion
        from jaeger_ai.contract.modes import normalize_interaction_tier
        from jaeger_agent.loop.runtime_bridge import (
            is_routine_lookup_turn, is_simple_or_chat_turn, turn_effort_hint,
        )
        _options = ((execution or {}).get("options") or {})
        _tier = normalize_interaction_tier((execution or {}).get("interaction_tier"))
        _effort_hint = "low" if is_simple_or_chat_turn(objective or prompt, _tier) else None
        # A turn-owned card runs in the chat's own session, so it must start from a
        # fresh ledger: resuming would hand it an earlier request's completion.
        turn_owned = bool(_options.get("turn_owned"))

        def stop_requested() -> bool:
            if self._cancellations.is_cancelled(request_id):
                return True
            # An owner decline is an answer, and an unanswered approval needs the owner:
            # neither is a stall to push the model through.
            return turn_owned and (request_id in self._owner_declined or request_id in self._owner_unanswered)

        from jaeger_ai.core.runtime.cron_turns import cron_turn_scope
        from jaeger_agent.core.workspace import project_scope
        try:
            _cron_steps = int(_options["max_steps"]) if _options.get("max_steps") is not None else None
        except (TypeError, ValueError):
            _cron_steps = None
        if _cron_steps is None:
            _cron_steps = (4 if turn_owned else 8) if _options.get("task_id") else None
        with project_scope((execution or {}).get("workspace") or None), cron_turn_scope(_options, session_id=session_key), ledger_scope(session_key, resume_completed=bool(_options.get("task_id")) and not bool(_options.get("verification_error")) and not turn_owned), turn_effort_hint(_effort_hint):
            try:
                result = run_continued_turn(
                    step, prompt, objective=objective or prompt,
                    durable=bool(_options.get("task_id")),
                    interactive=turn_owned,
                    max_steps=_cron_steps,
                    is_cancelled=stop_requested,
                    on_checkpoint=lambda checkpoint: self.event_bus.publish(
                        session_key, "turn.checkpoint", {**checkpoint, "request_id": request_id}),
                )
                if turn_owned and request_id in self._owner_unanswered and not self._cancellations.is_cancelled(request_id):
                    result = {**result, "halt_reason": "needs_owner", "error": None,
                              "evidence": {"approval_unanswered": True}}
                elif turn_owned and request_id in self._owner_declined and not self._cancellations.is_cancelled(request_id):
                    result = {**result, "halt_reason": "blocked", "error": None,
                              "evidence": {"declined_by_owner": True}}
                elif turn_owned and not result.get("error") and not stop_requested():
                    # One bounded correction, as a durable task gets: a completion with no
                    # file receipt is not something the owner can verify.
                    from jaeger_ai.core.runtime.autonomous_runner import missing_deliverable_paths
                    from jaeger_ai.core.tasks.owner import EVIDENCE_CONTRACT, has_file_receipt
                    # Only when the worker claimed completion without a file receipt, or
                    # the request names files that still do not exist. An answer-only
                    # request has no file to receipt; asking for one invites the model
                    # to invent an artifact.
                    completion = last_completion()
                    if not has_file_receipt(completion) and (
                            completion is not None or missing_deliverable_paths(objective or prompt)):
                        fix = step(
                            "Owner verification requires correction: your completion carried no receipt for a "
                            "file the owner can check. Finish the work if it is not done, then " + EVIDENCE_CONTRACT)
                        result = {**result, **fix, "text": fix.get("text") or result.get("text")}
                if timing is not None and "tool calls in a single turn" in str(result.get("halt_reason") or ""):
                    timing.halt_reason = result["halt_reason"]
                halt = str(result.get("halt_reason") or "")
                from jaeger_ai.core.runtime.continuation import is_loop_breaker
                if not result.get("error") and is_loop_breaker(halt) and halt not in {"needs_owner", "blocked", "yielded"}:
                    # A backstop is an incomplete run, even if the inner loop
                    # returned display text. Never record it as a final answer.
                    result = {**result, "status": "failed", "error": (
                        f"Jaeger stopped before completing this request ({halt}). "
                        "Completed tool actions remain recorded; review activity before retrying."
                    )}
                try:
                    self._maybe_queue_skill_review(
                        session_key, request_id, objective or prompt, result,
                        list(self._request_tools.get(request_id, [])), _options, _tier)
                except Exception:  # noqa: BLE001 — the nudge never affects the turn
                    logger.debug("skill review nudge skipped", exc_info=True)
                try:
                    self._maybe_queue_memory_review(session_key, request_id, result, _options, _tier)
                except Exception:  # noqa: BLE001 — the nudge never affects the turn
                    logger.debug("memory review nudge skipped", exc_info=True)
                return {**result, "task_completion": last_completion()}
            finally:
                self._active_agents.pop(request_id, None)
                self._request_tools.pop(request_id, None)
