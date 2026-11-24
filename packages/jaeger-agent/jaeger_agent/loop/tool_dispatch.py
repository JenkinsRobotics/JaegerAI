"""Extracted tool-dispatch & RW-parallel batching mixin for JaegerAgent (Wave 4B)."""
from __future__ import annotations

import threading
import time
from typing import Any

from jaeger_os.core.tools.tool_registry import get_tools
from jaeger_os.core.tools.tool_schema import ToolDef
from jaeger_agent.schemas.message_types import ToolCall
from .loop_backstop import call_signature, loop_warning, semantic_failure_signature
from jaeger_agent.skill_registry.tool_selection import tool_permitted
from .tool_result_safety import protect_tool_result


def _ja(name: str) -> Any:
    from . import jaeger_agent as _mod
    return getattr(_mod, name)


def _exclude_beta(*a: Any, **kw: Any) -> Any: return _ja("_exclude_beta")(*a, **kw)
def _filter_available_tools(*a: Any, **kw: Any) -> Any: return _ja("_filter_available_tools")(*a, **kw)
def _hash_result(*a: Any, **kw: Any) -> Any: return _ja("_hash_result")(*a, **kw)
def _merge_guidance(*a: Any, **kw: Any) -> Any: return _ja("_merge_guidance")(*a, **kw)
def _recovery_hint(*a: Any, **kw: Any) -> Any: return _ja("_recovery_hint")(*a, **kw)
def _stderr_tail(*a: Any, **kw: Any) -> Any: return _ja("_stderr_tail")(*a, **kw)
def _stringify(*a: Any, **kw: Any) -> Any: return _ja("_stringify")(*a, **kw)
def cancelled_tool_result(*a: Any, **kw: Any) -> Any: return _ja("cancelled_tool_result")(*a, **kw)
def in_agent_selection(*a: Any, **kw: Any) -> Any: return _ja("in_agent_selection")(*a, **kw)
def tool_result_failed(*a: Any, **kw: Any) -> Any: return _ja("tool_result_failed")(*a, **kw)


class AgentToolDispatchMixin:
    """Tool catalog refresh, RW-lock parallel read batching, dispatch and failure tracking."""

    def _refresh_tool_catalog(self) -> None:

        """Pick up tools registered AFTER this agent was built (skill
        installed / activated mid-session) so they become visible and
        dispatchable on the next turn. Honours the construction
        contract: an explicit ``tools=[...]`` allowlist never grows;
        a ``toolsets=`` agent re-resolves its categories; a default
        agent tracks the full registry. Beta tools stay excluded
        outside dev mode (re-checked per turn, so flipping
        ``JAEGER_DEV_MODE`` doesn't need an agent rebuild)."""
        if self._tools_filter_locked:
            self._tool_selection.catalog = tuple(
                _exclude_beta(get_tools()) if self._tools_filter_locked_reason == "overflow"
                else self._all_tools)
            return
        try:
            if self.toolsets:
                if self._toolset_resolver is None:
                    return
                wanted = self._toolset_resolver(set(self.toolsets))
                self._tool_selection.restricted = frozenset(wanted)
                self._all_tools = _filter_available_tools(
                    [t for t in get_tools() if t.name in wanted]
                )
            else:
                self._all_tools = _filter_available_tools(get_tools())
            self._dispatch_by_name = {t.name: t for t in self._all_tools}
            self._tool_selection.catalog = tuple(_exclude_beta(get_tools()))
        except Exception:  # noqa: BLE001 — a registry hiccup must not kill the turn
            pass

    def _batch_is_parallel_safe(self, tool_calls: list[ToolCall]) -> bool:
        """A batch may run concurrently when every call is either a
        ``side_effect="read"`` tool or a path-scoped file tool, none is
        interactive, and no two path-scoped calls touch overlapping paths
        where at least one is a write (two reads of the same file are fine).
        Unclassified tools are treated as write-side — conservative."""
        if len(tool_calls) < 2:
            return False
        scoped: list[tuple[str, bool]] = []   # (normpath, is_write)
        for tc in tool_calls:
            name = tc.get("name") or ""
            tool_def = self._dispatch_by_name.get(name)
            if tool_def is None:
                return False
            if getattr(tool_def, "interactive", False):
                return False
            if name in self._SERIAL_READ_TOOLS:
                return False
            is_read = getattr(tool_def, "side_effect", "") == "read"
            is_scoped = name in self._PATH_SCOPED_READ \
                or name in self._PATH_SCOPED_WRITE
            if not is_read and not is_scoped:
                return False                  # unknown write-side → serial
            if is_scoped:
                path = self._call_path(tc)
                if path is None:
                    return False              # path-scoped but no path → serial
                scoped.append((path, name in self._PATH_SCOPED_WRITE))
        # Conflict only when overlapping paths and at least one is a write.
        for i in range(len(scoped)):
            pi, wi = scoped[i]
            for j in range(i + 1, len(scoped)):
                pj, wj = scoped[j]
                if (wi or wj) and self._paths_overlap(pi, pj):
                    return False
        return True

    def _dispatch_parallel(self, tool_calls: list[ToolCall]) -> None:
        """Execute an all-read batch concurrently.

        Prepare and finish stay SERIAL and in batch order (callbacks,
        backstop counters, and the transcript are order-sensitive);
        only the tool functions themselves run on the pool. Duplicate
        signatures execute once — later twins reuse the first result
        via a duplicate marker, same as the sequential path.
        """
        from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
        from contextvars import copy_context

        preps = [self._prepare_dispatch(tc) for tc in tool_calls]
        first_by_sig: dict[str, int] = {}
        unique_idx: list[int] = []
        for i, prep in enumerate(preps):
            if prep["sig"] not in first_by_sig:
                first_by_sig[prep["sig"]] = i
                unique_idx.append(i)

        contents: dict[int, Any] = {}
        with ThreadPoolExecutor(
            max_workers=min(4, len(unique_idx)),
            thread_name_prefix="jaeger-tool",
        ) as pool:
            futures = {
                i: pool.submit(copy_context().run, self._execute_prepared, preps[i])
                for i in unique_idx
            }
            index = {future: i for i, future in futures.items()}
            for fut in as_completed(index):
                i = index[fut]
                try:
                    contents[i] = fut.result()
                except CancelledError:
                    contents[i] = cancelled_tool_result()
                except Exception as exc:  # noqa: BLE001 — belt: execute() shouldn't raise
                    contents[i] = {
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "error_type": "tool_error",
                        "retryable": True,
                    }
                if self._interrupt_event.is_set():
                    for pending in futures.values():
                        pending.cancel()

        for i, prep in enumerate(preps):
            owner = first_by_sig[prep["sig"]]
            if owner == i:
                self._finish_dispatch(prep, contents[owner])
            else:
                self._append_message({
                    "role": "tool",
                    "tool_call_id": prep["call_id"],
                    "name": prep["name"],
                    "content": _stringify({
                        "ok": True,
                        "duplicate_of": preps[owner]["call_id"] or "(first)",
                        "note": (
                            "identical call deduplicated this "
                            "iteration — see that result"
                        ),
                    }),
                })

    def _prepare_dispatch(self, tc: ToolCall) -> dict[str, Any]:
        """Serial pre-dispatch step: name normalisation, backstop
        pre-count for write-side tools, start callback, pre-dispatch
        guardrail hook."""
        name = tc.get("name") or ""
        args = tc.get("arguments") or {}
        call_id = tc.get("id") or ""

        # Resolve the tool against THIS agent's dispatch map (built
        # from ``_all_tools`` at construction). The previous code
        # asked the global registry, which silently bypassed an
        # explicit ``tools=[...]`` allowlist — a model that named any
        # globally registered tool could get it dispatched even when
        # the agent was supposed to expose only ``[a, b, c]``.
        dispatch_map = self._dispatch_by_name

        # Normalise drifted tool names ONCE at the loop boundary — case
        # variants, separator swaps, ``_tool`` suffixes, ``CamelCase``.
        # No fuzzy matching: an unrecognised name returns unchanged and
        # surfaces a clean "unknown tool" error so the model can
        # self-correct, rather than silently dispatching a guess.
        if name and name not in dispatch_map:
            # First resolve standard cross-framework aliases (e.g. bash -> terminal,
            # edit_file -> patch) ONLY to tools already present in dispatch_map
            # (never bypassing an explicit allowlist).
            _COMMON_ALIASES = {
                "bash": ("terminal", "exec_command", "run_shell"),
                "sh": ("terminal", "exec_command", "run_shell"),
                "shell": ("terminal", "exec_command", "run_shell"),
                "run_shell": ("terminal", "exec_command"),
                "run_command": ("terminal", "exec_command"),
                "edit_file": ("patch",),
                "str_replace": ("patch",),
                "str_replace_editor": ("patch",),
                "create_file": ("write_file",),
                "view_file": ("read_file",),
                "grep": ("search_files",),
                "grep_search": ("search_files",),
                "find_files": ("glob",),
                "list_dir": ("list_skill_dir",),
            }
            for _cand in _COMMON_ALIASES.get(name.strip().lower(), ()):
                if _cand in dispatch_map:
                    name = _cand
                    tc["name"] = name  # type: ignore[typeddict-item]
                    break
        if name and name not in dispatch_map:
            try:
                from jaeger_agent.dialects import normalize_tool_name
                valid = frozenset(dispatch_map.keys())
                normalised = normalize_tool_name(name, valid)
                if normalised != name and normalised in dispatch_map:
                    name = normalised
                    tc["name"] = name  # type: ignore[typeddict-item]
            except Exception:  # noqa: BLE001
                pass

        # Backstop bookkeeping. Write-side tools are counted *before*
        # dispatch so a tight loop trips the ceiling immediately rather
        # than after one extra wasted call. READ tools defer to the
        # post-dispatch result-hash check in ``_finish_dispatch`` —
        # re-issuing the same read while the answer is CHANGING is
        # legitimate polling, not a loop, so only a same-result repeat
        # counts.
        sig = call_signature(name, args)
        tool_def = dispatch_map.get(name)
        # Overflow (and unlocked agents) can leave dispatch_map behind the
        # live registry / describe_tool surface. Resolve once and cache.
        # Explicit tools=[...] allowlists must stay closed.
        if (
            tool_def is None
            and getattr(self, "_tools_filter_locked_reason", None) != "allowlist"
        ):
            try:
                _cands = _filter_available_tools(
                    [t for t in get_tools() if getattr(t, "name", None) == name]
                )
                if _cands:
                    tool_def = _cands[0]
                    self._dispatch_by_name[name] = tool_def
            except Exception:  # noqa: BLE001 — miss stays unknown_tool
                pass
        is_read_tool = (
            tool_def is not None
            and getattr(tool_def, "side_effect", "") == "read"
        )
        if not is_read_tool:
            self._read_result_cache.clear()
            self._call_signature_counts[sig] = (
                self._call_signature_counts.get(sig, 0) + 1
            )

        started = time.perf_counter()
        from jaeger_agent import live as _live
        _sub = _live.current_subagent()
        live_call = f"{_sub}:{call_id}" if _sub else call_id
        with _live.tool_call(live_call):
            self.callbacks.on_tool_progress(name, "start", args)
            if _sub:
                _live.emit("subagent.tool.started", {"subagent_id": _sub, "call_id": live_call, "tool": name})
        # Pre-dispatch hook — guardrail returns optional guidance text.
        guidance = self.callbacks.on_before_tool_call(name, args)
        return {
            "name": name,
            "args": args,
            "call_id": call_id, "live_call": live_call,
            "sig": sig,
            "tool_def": tool_def,
            "is_read": is_read_tool,
            "guidance": guidance,
            "started": started,
        }

    def _execute_cli_mcp_tool(self, tool: ToolDef | str, arguments: dict[str, Any]) -> Any:
        """Run one Jaeger tool for a CLI-brain MCP call.

        Uses the same prepare / execute / finish path as the agent loop so
        permissions, approvals, guardrails, and events stay identical.
        Serialized because the MCP server may call in from a worker thread
        while the model call is blocked.
        """
        import uuid
        name = tool.name if isinstance(tool, ToolDef) else str(tool)
        args = dict(arguments or {})
        call_id = f"mcp-{uuid.uuid4().hex[:16]}"
        tc: ToolCall = {"id": call_id, "name": name, "arguments": args}
        lock = getattr(self, "_cli_mcp_lock", None)
        if lock is None:
            lock = self._cli_mcp_lock = threading.Lock()
        with lock:
            self._append_message({
                "role": "assistant",
                "content": "",
                "tool_calls": [tc],
            })
            prep = self._prepare_dispatch(tc)
            content = self._execute_prepared(prep)
            self._finish_dispatch(prep, content)
            return content

    @in_agent_selection
    def _execute_prepared(self, prep: dict[str, Any]) -> Any:
        """The actual tool call — the only part safe to run off-thread
        for read-only tools. Exceptions become error-result dicts."""
        name = prep["name"]
        args = prep["args"]
        if self._interrupt_event.is_set():
            return cancelled_tool_result()
        if not tool_permitted(name):
            from jaeger_agent.skill_registry.tool_selection import tool_denial_reason
            why = tool_denial_reason(name) or "scope"
            import logging as _logging
            _logging.getLogger("jaeger.tool_scope").warning("tool %s denied: %s", name, why)
            return {"ok": False, "error": f"Tool is outside this request scope ({why})", "error_type": "permission_denied", "retryable": False}
        if name in self._CACHEABLE_READ_TOOLS and prep["sig"] in self._read_result_cache:
            import copy
            prep["cache_hit"] = True
            return copy.deepcopy(self._read_result_cache[prep["sig"]])
        try:
            tool_def = prep["tool_def"]
            if tool_def is None:
                content: Any = {
                    "ok": False,
                    "error": f"unknown tool {name!r}",
                    "error_type": "unknown_tool",
                    "retryable": False,
                }
            else:
                # A started tool must see THIS turn's interrupt, not only the loop between
                # nodes: bind the turn's own event for the call so a cancel or Global Stop
                # reaches a running command (tool_interrupt.is_interrupted reads it).
                from jaeger_agent.core.cancellation import turn_cancellation
                from jaeger_agent import live as _live
                # The call id rides a ContextVar so delegates, progress and
                # hooks inside the tool report under THIS call's span.
                with turn_cancellation(self._interrupt_event), _live.tool_call(prep.get("live_call") or prep.get("call_id")):
                    content = self._tool_executor.execute(tool_def, args)
        except Exception as exc:  # noqa: BLE001 — surfaced to the model
            # Tag safety/permission failures distinctly so the model
            # (and the latency log) can tell "retry with different
            # args" from "user said no, don't try again". The legacy
            # generic-catch lumped them together and the model would
            # cheerfully retry a denied PRIVILEGED call.
            err_type = "tool_error"
            retryable = True
            required_tier: str | None = None
            try:
                from jaeger_os.core.safety.permissions import (
                    PermissionDenied,
                    ConfirmationRequired,
                    HumanOverrideRequired,
                )
                if isinstance(exc, (PermissionDenied,
                                    ConfirmationRequired,
                                    HumanOverrideRequired)):
                    err_type = "permission_denied"
                    retryable = False
                    required_tier = getattr(exc, "tier", None) or getattr(
                        exc, "required_tier", None,
                    )
            except Exception:  # noqa: BLE001 — never break the loop over typing
                pass
            try:
                from jaeger_agent.cognition.effects import (
                    EffectIndeterminate, EffectOutcomeUnknown,
                )
                if isinstance(exc, (EffectIndeterminate, EffectOutcomeUnknown)):
                    err_type = "effect_indeterminate"
                    retryable = False
            except Exception:  # noqa: BLE001
                pass
            try:
                from jaeger_agent.core.workspace import ReadAccessDenied
                if isinstance(exc, ReadAccessDenied):
                    err_type = "permission_denied"
                    retryable = False
            except Exception:  # noqa: BLE001
                pass
            # Hardline guard refusals (run_shell catastrophic-command
            # blocklist) come back as a typed dict, not an exception;
            # they don't land here. But if a future refusal layer
            # raises, treat it the same as permission_denied.
            content = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "error_type": err_type,
                "retryable": retryable,
            }
            if required_tier:
                content["required_tier"] = str(required_tier)
        return content

    def _finish_dispatch(self, prep: dict[str, Any], content: Any) -> None:
        """Serial post-dispatch step: truncation, hooks, observability,
        backstop counting, warning injection, append. Must run in batch
        order — counters and the transcript are order-sensitive."""
        name = prep["name"]
        args = prep["args"]
        call_id = prep["call_id"]
        sig = prep["sig"]
        is_read_tool = prep["is_read"]
        guidance = prep["guidance"]
        started = prep["started"]
        self._turn_tool_names.append(name)

        # Determine outcome before truncation/hooks can replace a structured
        # error with an artifact pointer. An error-only envelope is a failure.
        _ok = not tool_result_failed(content)
        _err = str(content.get("error") or content.get("reason") or _stderr_tail(content)
                   or "tool failed") if not _ok else None

        # Track behavioral task stage & convergence alarms via standalone jaeger-loop
        ctrl = getattr(self, "_convergence", None)
        if ctrl is not None:
            tool_names = set(self._dispatch_by_name.keys())
            conv_hint = ctrl.record_tool_result(
                name,
                args if isinstance(args, dict) else None,
                ok=_ok,
                has_edit_tool=bool({"write_file", "patch", "edit_file", "apply_patch"} & tool_names),
                has_verify_tool=bool({"terminal", "execute_code", "run_shell", "run_python", "bash"} & tool_names),
            )
            if conv_hint:
                guidance = f"{guidance}\n{conv_hint}".strip() if guidance else conv_hint

        # Per-tool-result oversize guard. A single ``run_shell`` dump
        # or screenshot can dominate the next turn's context; cap it
        # here so the history-trim pass downstream isn't fighting a
        # losing battle. Runs before the user-provided after_tool_call
        # hook so an external budget (if any) sees the trimmed shape.
        if self.context_guard is not None:
            content, truncated = self.context_guard.truncate_oversized_result(content)
            if truncated:
                self.callbacks.on_thinking(
                    f"[context-guard] truncated oversized {name!r} result"
                )

        # Post-dispatch hook — budget can substitute a pointer if the
        # payload is oversized. ``None`` means "leave content alone".
        replacement = self.callbacks.on_after_tool_call(name, args, content)
        if replacement is not None:
            content = replacement
        if guidance:
            content = _merge_guidance(content, guidance)
        if not _ok and isinstance(content, dict) and "recovery" not in content:
            recovery = (
                "This authority decision is definitive for the current scope. Do not retry "
                "the same path or use another tool to bypass it; report the blocker and stop."
                if content.get("retryable") is False
                else _recovery_hint(name, args, _err)
            )
            content = {**content, "recovery": recovery}

        elapsed = time.perf_counter() - started
        from jaeger_agent import live as _live
        _sub = _live.current_subagent()
        _call_scope = _live.tool_call(f"{_sub}:{call_id}" if _sub else call_id)
        _call_scope.__enter__()
        self.callbacks.on_tool_progress(
            name, "done", {"elapsed_s": round(elapsed, 3)},
        )
        tool_def = prep.get("tool_def")

        # Passive observer for the tool_calls audit table. Determine
        # ok/error from the final content shape: dispatch-raised paths
        # built a ``{"ok": False, "error": ...}`` dict above; a tool
        # returning a successful payload won't carry ``"ok": False``.
        if tool_result_failed(content):
            _ok = False
            _err = str(content.get("error") or "") or None
        if _ok and name in self._CACHEABLE_READ_TOOLS:
            import copy
            self._read_result_cache[sig] = copy.deepcopy(content)
        if _ok:
            if name == "use_skill" and isinstance(args, dict):
                chosen = str(args.get("name") or "").strip()
                if chosen:
                    self._turn_skill_names.add(chosen)
        try:
            self.callbacks.on_tool_done(
                name, dict(args) if isinstance(args, dict) else {},
                content, _ok, _err, round(elapsed, 6),
            )
            if _sub:
                _live.emit("subagent.tool.finished", {"subagent_id": _sub,
                                                      "call_id": f"{_sub}:{call_id}", "tool": name,
                                                      "ok": bool(_ok), "elapsed_s": round(elapsed, 3)})
        finally:
            _call_scope.__exit__(None, None, None)

        # Usage counters (``logs/usage.json``). ``record_skill`` was wired
        # up from the skill tool, but its tool counterpart had no callers
        # anywhere — so the sidecar's ``"tools"`` map stayed permanently
        # empty and ``/usage`` could only ever report skill views. This is
        # the single point every dispatched tool passes through with its
        # outcome and duration already resolved, so count it here rather
        # than at each call site. Best-effort: telemetry never breaks a turn.
        # Two sinks, each counted once: the agent-local usage registry
        # (sidecar ``/usage``, skills curation) and the product-injected
        # stats via the callbacks dependency inversion.
        self.callbacks.on_record_tool(name, ok=_ok, elapsed=elapsed)
        try:
            from jaeger_agent.core.usage import record_tool
            record_tool(name, ok=_ok, elapsed=elapsed)
        except Exception:  # noqa: BLE001
            pass

        # File-mutation verifier bookkeeping: remember failures per
        # (tool, path); a later SUCCESS on the same target supersedes.
        # Un-superseded failures surface in the final-answer footer.
        if name in _ja('_MUTATION_TOOLS'):
            target = ""
            if isinstance(args, dict):
                target = str(args.get("path") or args.get("file") or "")
            mkey = (name, target)
            if _ok:
                self._failed_mutations.pop(mkey, None)
                # Editing source files is real TDD progress — reset stale
                # shell/test failure streaks so re-running pytest does not
                # trip the 2-strike loop backstop.
                for _fkey in [
                    k for k in self._failure_signature_counts
                    if k.startswith(("terminal|", "exec_command|", "execute_code|", "run_python|"))
                ]:
                    self._failure_signature_counts.pop(_fkey, None)
            else:
                self._failed_mutations[mkey] = (_err or "failed")[:120]

        # Failure-signature tracking — only meaningful when the tool
        # returns an explicit failure dict. Successful calls drop out
        # of this counter via ``semantic_failure_signature``'s None
        # return. When a shell/exec command succeeds, clear stale failure
        # streaks for that tool family so non-consecutive debugging runs
        # do not accumulate into a false 2-strike kill.
        fail_sig = semantic_failure_signature(name, args, content)
        if fail_sig is not None:
            self._failure_signature_counts[fail_sig] = (
                self._failure_signature_counts.get(fail_sig, 0) + 1
            )
        elif _ok and name in ("terminal", "exec_command", "execute_code", "run_python", "run_shell"):
            for _fkey in [
                k for k in self._failure_signature_counts
                if k.startswith((f"{name}|", "terminal|", "exec_command|"))
            ]:
                self._failure_signature_counts.pop(_fkey, None)

        # Deferred identical-call counting for READ tools: a repeat
        # only counts when the result is byte-identical to the last
        # one (no progress). A changed result resets the streak.
        if is_read_tool:
            result_hash = _hash_result(content)
            if self._read_result_hashes.get(sig) == result_hash:
                self._call_signature_counts[sig] = (
                    self._call_signature_counts.get(sig, 0) + 1
                )
            else:
                self._read_result_hashes[sig] = result_hash
                self._call_signature_counts[sig] = 1

        # Warn-before-halt: when this call is one step from tripping
        # the backstop, ride guidance on the result so the model can
        # change course instead of dying at the halt. Never blocks.
        warning = loop_warning(
            self._call_signature_counts,
            self._failure_signature_counts,
            sig=sig,
            fail_sig=fail_sig,
        )
        if warning:
            content = _merge_guidance(content, warning)

        rendered_content = (
            content if isinstance(content, str) else _stringify(content)
        )
        rendered_content = protect_tool_result(name, rendered_content)
        tool_message = {
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": rendered_content,
        }
        self._append_message(tool_message)
        if (
            self._effect_checkpoint is not None
            and tool_def is not None
            and getattr(tool_def, "side_effect", "") != "read"
        ):
            self._effect_checkpoint(
                name,
                dict(args) if isinstance(args, dict) else {},
                dict(tool_message),
            )

    def _finalize_skip_final(
        self,
        tool_name: str,
        tool_result: Any,
        user_message: str,
    ) -> str:
        """Call the skip-final finalizer to phrase the tool result and
        append a synthetic assistant message for history continuity.

        Doing the append here (rather than letting the finalizer mutate
        the message list) means the next turn sees a clean
        user → assistant(tool_call) → tool → assistant transcript, even
        though the second assistant text was produced by the finalizer
        path instead of the main model loop.
        """
        self.last_skip_final = True
        try:
            answer = self.skip_final_finalizer(
                tool_name, tool_result, user_message,
            )
        except Exception as exc:  # noqa: BLE001 — finaliser bugs degrade gracefully
            answer = (
                f"[skip-final finalizer failed: {type(exc).__name__}; "
                f"raw result: {tool_result}]"
            )
        self._append_message({"role": "assistant", "content": answer})
        self.callbacks.on_step(self.last_iteration_count + 1, self.messages[-1])
        return answer
