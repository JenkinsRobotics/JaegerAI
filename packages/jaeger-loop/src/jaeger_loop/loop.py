"""Pure composable AgentLoop implementing ExecutionLoopPort.

Replaces the 2,943-LOC monolithic `jaeger_agent.py` with a clean ~200-LOC loop
combining the strongest donor patterns:
- ag2 (`agent.py`, `middleware/base.py`): onion Middleware wrapping model/tool calls
- hermes-agent (`conversation_loop.py`, `turn_*.py`): explicit TurnVerdict phases
- openai-codex (`tools/parallel.rs`): RW-lock-partitioned parallel tool execution
  (consecutive read-only tool calls execute concurrently; mutating calls serialize)
- Integrated with `ModelPort`, `ToolPort`, `StateMemoryPort`, `ReliabilityPort`,
  and `EventBusPort` (zero coupling to `jaeger_ai`).
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from jaeger_contracts import (
    EventBusPort,
    ModelPort,
    ReliabilityPort,
    StateMemoryPort,
    ToolPort,
    ToolResult,
)
from jaeger_memory.compactor import (
    compact_messages,
    estimate_compactor_tokens,
    should_compact,
)


class TurnVerdict(str, Enum):
    COMPLETE = "complete"
    LOOP_HALTED = "loop_halted"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ERROR = "error"


@dataclass
class TurnContext:
    session_id: str
    messages: list[dict[str, Any]]
    step: int = 0
    tool_history: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class LoopMiddleware(Protocol):
    """Onion middleware hook around model calls and tool executions (ag2 pattern)."""

    def on_model_call(
        self,
        ctx: TurnContext,
        call_next: Callable[[TurnContext], Mapping[str, Any]],
    ) -> Mapping[str, Any]: ...

    def on_tool_call(
        self,
        ctx: TurnContext,
        tool_name: str,
        arguments: Mapping[str, Any],
        call_next: Callable[[str, Mapping[str, Any]], ToolResult],
    ) -> ToolResult: ...


def partition_read_write_batches(
    items: Sequence[Any],
    is_read_only: Callable[[Any], bool],
) -> list[tuple[bool, list[Any]]]:
    """RW-lock batch partitioner (openai-codex parallel.rs pattern).

    Groups consecutive read-only items into parallel batches ``(True, [...])``
    while keeping each mutating item as a single serial batch ``(False, [item])``.
    """
    batches: list[tuple[bool, list[Any]]] = []
    i = 0
    n = len(items)
    while i < n:
        if is_read_only(items[i]):
            run: list[Any] = []
            while i < n and is_read_only(items[i]):
                run.append(items[i])
                i += 1
            batches.append((True, run))
        else:
            batches.append((False, [items[i]]))
            i += 1
    return batches


_CODE_EDIT_TOOLS = frozenset({
    "write_file", "patch", "edit_file", "apply_patch", "notebook_edit", "append_file",
})
_VERIFY_TOOLS = frozenset({
    "terminal", "execute_code", "run_shell", "run_python", "bash", "shell", "exec_command",
})
_CODE_EXTENSIONS = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".c", ".cpp", ".h", ".hpp", ".java", ".swift", ".rb",
})


class PostEditVerificationGuard:
    """Single-shot verification guard ensuring code edits are tested before concluding.

    Tracks code-file mutations across a turn and clears the dirty flag whenever
    a verification/shell tool runs. If the model attempts to finish with
    unverified code edits (and a verification tool is available), returns a
    one-shot verification nudge asking for `git diff` + targeted edge-case tests.
    """

    def __init__(self, *, max_nudges: int = 1) -> None:
        self._max_nudges = max(0, int(max_nudges))
        self.reset()

    def reset(self) -> None:
        self.mutated_files: list[str] = []
        self.needs_verification: bool = False
        self.nudges_used: int = 0

    def record_tool_result(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        ok: bool = True,
    ) -> None:
        name = (tool_name or "").strip().lower()
        if name in _VERIFY_TOOLS:
            self.needs_verification = False
            return
        if not ok or name not in _CODE_EDIT_TOOLS:
            return
        args = dict(arguments or {})
        raw_path = str(args.get("path") or args.get("file_path") or args.get("target") or "").strip()
        if name == "apply_patch" and not raw_path:
            # Multi-file patch always qualifies as a code edit
            self.needs_verification = True
            if "<patch>" not in self.mutated_files:
                self.mutated_files.append("<patch>")
            return
        lower = raw_path.lower()
        if any(lower.endswith(ext) for ext in _CODE_EXTENSIONS):
            self.needs_verification = True
            if raw_path not in self.mutated_files:
                self.mutated_files.append(raw_path)

    def maybe_nudge(self, *, has_verify_tool: bool = True) -> str | None:
        if not has_verify_tool or not self.needs_verification or self.nudges_used >= self._max_nudges:
            return None
        self.nudges_used += 1
        files = ", ".join(self.mutated_files[-5:]) or "code files"
        return (
            f"You modified code ({files}) since your last test/command run. "
            "Before giving your final answer, inspect `git diff` and run targeted tests "
            "(including edge cases) to verify your change works with zero regressions."
        )


_READ_TOOLS = frozenset({
    "read_file", "read_many_files", "search_files", "list_skill_dir", "glob", "repo_map",
    "search_offloaded_output", "list_tools", "describe_tool", "tool_search", "web_fetch",
})
_ARTIFACT_RE = re.compile(
    r"(?:write|create|save|output|produce|generate|implement|update|into|as|to)\s+"
    r"(?:a\s+|the\s+|file\s+|module\s+|script\s+)*"
    r"[`'\"]?([A-Za-z0-9_./-]+\.(?:py|json|txt|md|csv|yaml|yml|toml|sh|ts|tsx|js|jsx))[`'\"]?",
    re.IGNORECASE,
)


def extract_requested_artifacts(prompt: str) -> tuple[str, ...]:
    """Deterministically extract workspace output filenames explicitly requested in a prompt."""
    found: list[str] = []
    for m in _ARTIFACT_RE.finditer(prompt or ""):
        cand = m.group(1).strip().lstrip("./")
        if not cand or ".." in cand or cand.startswith("/") or cand.startswith("http"):
            continue
        if cand not in found:
            found.append(cand)
    return tuple(found[:8])


class TaskConvergenceController:
    """Stage-aware behavioral budget & artifact convergence guard (localize -> edit -> verify -> report).

    Composes ``PostEditVerificationGuard`` with behavioral stall alarms:
      1. Read/search stall without any workspace edit or hypothesis test.
      2. Repeated edits (>=3) without running a targeted verification command.
      3. Consecutive shell/test failures (>=3) requiring strategy shift.
      4. Missing explicitly requested workspace output artifacts on candidate finish.
    """

    def __init__(
        self,
        prompt: str = "",
        *,
        max_read_stall: int = 8,
        max_untested_edits: int = 3,
        max_shell_failures: int = 3,
        max_finish_nudges: int = 2,
    ) -> None:
        self._max_read_stall = max(3, int(max_read_stall))
        self._max_untested_edits = max(2, int(max_untested_edits))
        self._max_shell_failures = max(2, int(max_shell_failures))
        self._max_finish_nudges = max(0, int(max_finish_nudges))
        self._verify_guard = PostEditVerificationGuard(max_nudges=1)
        self.reset(prompt)

    def reset(self, prompt: str = "") -> None:
        self._verify_guard.reset()
        self.expected_artifacts: tuple[str, ...] = extract_requested_artifacts(prompt)
        self.stage: str = "localize"
        self.read_calls_since_edit: int = 0
        self.edits_since_verify: int = 0
        self.shell_failures_in_row: int = 0
        self.finish_nudges_used: int = 0
        self._artifact_nudge_used: bool = False
        self._read_alarm_fired: bool = False
        self._edit_alarm_fired: bool = False
        self._shell_alarm_fired: bool = False

    @property
    def mutated_files(self) -> list[str]:
        return self._verify_guard.mutated_files

    @property
    def needs_verification(self) -> bool:
        return self._verify_guard.needs_verification

    def record_tool_result(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        ok: bool = True,
        has_edit_tool: bool = True,
        has_verify_tool: bool = True,
    ) -> str | None:
        """Record one tool execution and return a strategy-shift hint if a stall alarm trips."""
        self._verify_guard.record_tool_result(tool_name, arguments, ok=ok)
        name = (tool_name or "").strip().lower()

        if name in _CODE_EDIT_TOOLS and ok:
            self.stage = "edit"
            self.read_calls_since_edit = 0
            self.edits_since_verify += 1
            self.shell_failures_in_row = 0
            self._shell_alarm_fired = False
            if (
                has_verify_tool
                and not self._edit_alarm_fired
                and self.edits_since_verify >= self._max_untested_edits
            ):
                self._edit_alarm_fired = True
                return (
                    f"STRATEGY SHIFT (edit -> verify): You made {self.edits_since_verify} code edits "
                    "without running a test/verification check. Pause editing, inspect `git diff`, "
                    "and run the narrowest targeted test now."
                )
            return None

        if name in _VERIFY_TOOLS:
            self.stage = "verify"
            self.edits_since_verify = 0
            self._edit_alarm_fired = False
            if ok:
                self.shell_failures_in_row = 0
                self._shell_alarm_fired = False
            else:
                self.shell_failures_in_row += 1
                if not self._shell_alarm_fired and self.shell_failures_in_row >= self._max_shell_failures:
                    self._shell_alarm_fired = True
                    return (
                        f"STRATEGY SHIFT (repeated failures): {self.shell_failures_in_row} consecutive "
                        "command failures. Re-read the exact traceback/error and inspect the failing "
                        "file directly instead of retrying similar commands."
                    )
            return None

        if name in _READ_TOOLS:
            self.read_calls_since_edit += 1
            if (
                not self._read_alarm_fired
                and not self.mutated_files
                and self.read_calls_since_edit >= self._max_read_stall
            ):
                self._read_alarm_fired = True
                if has_edit_tool:
                    return (
                        f"STRATEGY SHIFT: You have made {self.read_calls_since_edit} read/search/fetch calls "
                        "without acting or answering. Either apply your targeted edit now or synthesize "
                        "what you already verified and answer the user directly."
                    )
                return (
                    f"STRATEGY SHIFT: You have made {self.read_calls_since_edit} read/search/fetch calls "
                    "in this turn. Stop exploring and synthesize a direct answer from the evidence already gathered."
                )
        return None

    def missing_artifacts(self, workspace: Path | str | None) -> list[str]:
        if not workspace or not self.expected_artifacts:
            return []
        ws = Path(workspace)
        if not ws.is_dir():
            return []
        missing: list[str] = []
        for rel in self.expected_artifacts:
            cand = ws / rel
            if not cand.exists():
                # Also tolerate top-level basename match when prompt omitted subdir
                if "/" not in rel and any(ws.glob(f"*/{rel}")):
                    continue
                missing.append(rel)
        return missing

    def maybe_finish_nudge(
        self,
        *,
        workspace: Path | str | None = None,
        has_verify_tool: bool = True,
        has_edit_tool: bool = True,
    ) -> str | None:
        """Check missing requested artifacts and unverified code edits before concluding."""
        if self.finish_nudges_used >= self._max_finish_nudges:
            return None
        if has_edit_tool and not self._artifact_nudge_used:
            missing = self.missing_artifacts(workspace)
            if missing:
                self._artifact_nudge_used = True
                self.finish_nudges_used += 1
                return (
                    f"MISSING ARTIFACT: The request asked to produce {', '.join(missing)}, "
                    "which does not exist in the workspace yet. Create and verify it before concluding."
                )
        verify_nudge = self._verify_guard.maybe_nudge(has_verify_tool=has_verify_tool)
        if verify_nudge:
            self.finish_nudges_used += 1
            return verify_nudge
        self.stage = "report"
        return None


class AgentLoop:
    """Clean, standalone, middleware-composable ExecutionLoopPort."""

    def __init__(
        self,
        *,
        model: ModelPort,
        tools: ToolPort,
        memory: StateMemoryPort | None = None,
        reliability: ReliabilityPort | None = None,
        events: EventBusPort | None = None,
        middlewares: Sequence[LoopMiddleware] = (),
        system_prompt: str = "You are Jaeger, an autonomous engineering agent.",
        max_context_tokens: int | None = None,
        compact_threshold: float | None = None,
        session_id: str = "default",
        name: str = "jaeger_loop",
        verify_after_edit: bool = False,
    ) -> None:
        self._name = name
        self._model = model
        self._tools = tools
        self._memory = memory
        self._reliability = reliability
        self._events = events
        self._middlewares = list(middlewares)
        self._system_prompt = system_prompt
        self._max_context_tokens = max_context_tokens
        self._compact_threshold = compact_threshold
        self._window = self._resolve_window()
        self._session_id = session_id
        self._verify_after_edit = bool(verify_after_edit)

    @property
    def name(self) -> str:
        return self._name

    def _resolve_window(self) -> int:
        """Real model context window: ModelPort.profile -> JAEGER_CTX_WINDOW -> 24k fallback."""
        try:
            profile = self._model.profile(getattr(self._model, "model_id", self._model.name))
            window = int(getattr(profile, "context_window", 0) or 0)
            if window > 0:
                return window
        except Exception:  # noqa: BLE001 - profile lookup must never break the loop
            pass
        env_window = os.environ.get("JAEGER_CTX_WINDOW", "").strip()
        if env_window:
            try:
                window = int(env_window)
                if window > 0:
                    return window
            except ValueError:
                pass
        return 24_000

    def select_history(self, prompt: str, newest_first: Iterable[dict[str, str]]) -> list[dict[str, str]]:
        """Keep the newest complete session messages that fit before the current turn."""
        llm_tools = [
            {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "schema": t.get("schema", {}),
            }
            for t in self._tools.list_tools()
        ]
        schemas = json.dumps(llm_tools, ensure_ascii=False, separators=(",", ":"), default=str)
        used = estimate_compactor_tokens([{"content": prompt}, {"content": schemas}],
                                         system_prompt=self._system_prompt)
        min_history_floor = min(int(self._window * 0.20), 2048)
        remaining = max(int(self._window * 0.75) - used, min_history_floor)
        history = []
        for message in newest_first:
            cost = 4 + estimate_compactor_tokens([message])
            if cost > remaining:
                break
            history.append(message)
            remaining -= cost
        return history[::-1]

    def _compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Percentage-of-window compaction (default 80%, JAEGER_COMPACT_AT) with a
        fixed-token fallback when no window is known. Emits context.compacted events."""
        window = self._window
        used = estimate_compactor_tokens(messages)
        if should_compact(
            messages,
            ctx_window=window,
            used_tokens=used,
            threshold=self._compact_threshold,
            system_prompt=self._system_prompt,
        ):
            before = len(messages)
            messages = compact_messages(
                messages,
                ctx_window=window,
                used_tokens=used,
                threshold=self._compact_threshold,
                system_prompt=self._system_prompt,
            )
            self._emit("context.compacted", {
                "used_tokens": used,
                "ctx_window": window,
                "messages_before": before,
                "messages_after": len(messages),
            })
            return messages
        if self._max_context_tokens is not None:
            return self._memory.compact(messages, max_tokens=self._max_context_tokens) if self._memory is not None else messages
        return messages

    def _emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if self._events is not None:
            self._events.publish(event_type, payload, session_id=self._session_id)

    def _invoke_model(self, ctx: TurnContext, *, allow_tools: bool = True) -> Mapping[str, Any]:
        def base(c: TurnContext) -> Mapping[str, Any]:
            tool_schemas = list(self._tools.list_tools()) if allow_tools else []
            return self._model.complete(c.messages, tools=tool_schemas)

        chain = base
        for mw in reversed(self._middlewares):
            prev = chain
            chain = lambda c, m=mw, nxt=prev: m.on_model_call(c, nxt)
        return chain(ctx)

    def _resolve_tool_name(self, tool_name: str) -> str:
        if self._reliability is not None and hasattr(self._reliability, "resolve_tool_alias"):
            try:
                return str(self._reliability.resolve_tool_alias(tool_name))
            except Exception:  # noqa: BLE001
                return tool_name
        return tool_name

    def _invoke_tool(self, ctx: TurnContext, tool_name: str, raw_args: Any) -> ToolResult:
        tool_name = self._resolve_tool_name(tool_name)
        args: Mapping[str, Any]
        if self._reliability is not None:
            spec = getattr(self._tools, "get_spec", lambda _n: None)(tool_name)
            schema = spec.schema if spec is not None else {}
            try:
                args = self._reliability.repair_arguments(tool_name, raw_args, schema)
            except Exception as exc:
                return ToolResult(tool_name=tool_name, ok=False, error=f"Argument repair failed: {exc}")
        elif isinstance(raw_args, Mapping):
            args = dict(raw_args)
        else:
            return ToolResult(tool_name=tool_name, ok=False, error="Malformed non-dict tool arguments.")

        def base(name: str, a: Mapping[str, Any]) -> ToolResult:
            return self._tools.execute(name, a)

        chain = base
        for mw in reversed(self._middlewares):
            prev = chain
            chain = lambda n, a, m=mw, nxt=prev: m.on_tool_call(ctx, n, a, nxt)
        return chain(tool_name, args)

    def _is_read_only(self, tool_name: str) -> bool:
        resolved = self._resolve_tool_name(tool_name)
        spec = getattr(self._tools, "get_spec", lambda _n: None)(resolved)
        return bool(spec and getattr(spec, "read_only", False))

    def _execute_tool_batch(
        self, ctx: TurnContext, tool_calls: Sequence[Mapping[str, Any]]
    ) -> list[tuple[Mapping[str, Any], ToolResult]]:
        """RW-lock-partitioned execution: parallel for consecutive read-only calls, serial for writes."""
        results: list[tuple[Mapping[str, Any], ToolResult]] = []
        i = 0
        n = len(tool_calls)
        while i < n:
            if self._is_read_only(str(tool_calls[i].get("name") or "")):
                batch: list[Mapping[str, Any]] = []
                while i < n and self._is_read_only(str(tool_calls[i].get("name") or "")):
                    batch.append(tool_calls[i])
                    i += 1
                if len(batch) > 1:
                    with ThreadPoolExecutor(max_workers=min(8, len(batch))) as pool:
                        futs = [
                            (tc, pool.submit(self._invoke_tool, ctx, str(tc.get("name") or ""), tc.get("arguments", {})))
                            for tc in batch
                        ]
                        for tc, fut in futs:
                            results.append((tc, fut.result()))
                else:
                    tc = batch[0]
                    results.append((tc, self._invoke_tool(ctx, str(tc.get("name") or ""), tc.get("arguments", {}))))
            else:
                tc = tool_calls[i]
                results.append((tc, self._invoke_tool(ctx, str(tc.get("name") or ""), tc.get("arguments", {}))))
                i += 1
        return results

    def run_turn(
        self,
        prompt: str,
        *,
        max_steps: int = 20,
        extra_slices: int = 0,
        pre_slice_guard: Any = None,
        history: Sequence[Mapping[str, Any]] = (),
        mailbox: Any = None,
        cancel_scope: Any = None,
    ) -> Mapping[str, Any]:
        from .primitives import MailPriority, instantiate_middlewares_for_run

        saved_middlewares = self._middlewares
        self._middlewares = instantiate_middlewares_for_run(saved_middlewares, self._session_id)
        try:
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": self._system_prompt},
                *(dict(message) for message in history),
                {"role": "user", "content": prompt},
            ]
            ctx = TurnContext(session_id=self._session_id, messages=messages)
            verify_guard = PostEditVerificationGuard(max_nudges=1) if self._verify_after_edit else None
            convergence = TaskConvergenceController(prompt)
            available_tool_names = {
                str(t.get("name") or "").strip().lower()
                for t in (self._tools.list_tools() or ())
                if isinstance(t, Mapping)
            }
            has_edit_tool = bool(available_tool_names & _CODE_EDIT_TOOLS)
            has_verify_tool = bool(available_tool_names & _VERIFY_TOOLS)
            empty_recovery_used = False
            self._emit("turn.start", {"prompt": prompt, "max_steps": max_steps})

            slice_steps = max(1, max_steps)
            total_steps = slice_steps * (1 + min(2, max(0, extra_slices)))
            for step in range(1, total_steps + 1):
                if cancel_scope is not None and getattr(cancel_scope, "is_cancelled", False):
                    self._emit("turn.cancelled", {"step": step})
                    return {
                        "verdict": TurnVerdict.LOOP_HALTED.value,
                        "content": "Cancelled by CancelScope.",
                        "steps": step - 1,
                        "messages": ctx.messages,
                    }
                if mailbox is not None:
                    incoming = mailbox.drain()
                    for m in incoming:
                        if m.priority == MailPriority.ABORT:
                            self._emit("turn.aborted", {"step": step, "reason": m.content})
                            return {
                                "verdict": TurnVerdict.LOOP_HALTED.value,
                                "content": f"Aborted: {m.content}",
                                "steps": step - 1,
                                "messages": ctx.messages,
                            }
                        ctx.messages.append({"role": "user", "content": f"[STEER] {m.content}"})

                ctx.step = step
                ctx.messages = self._compact(ctx.messages)

                if step > slice_steps and (step - 1) % slice_steps == 0:
                    if pre_slice_guard is not None and pre_slice_guard():
                        self._emit("turn.estop_halted", {"step": step})
                        return {
                            "verdict": TurnVerdict.LOOP_HALTED.value,
                            "content": "Halted by E-Stop before continuation slice.",
                            "steps": step - 1,
                            "messages": ctx.messages,
                        }
                    self._emit("turn.continued", {"step": step, "slice_steps": slice_steps})
                self._emit("step.model_start", {"step": step})
                resp = self._invoke_model(ctx)
                content = str(resp.get("content") or "")
                tool_calls = list(resp.get("tool_calls") or [])

                assistant_msg: dict[str, Any] = {"role": "assistant", "content": content}
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                ctx.messages.append(assistant_msg)

                if not tool_calls:
                    if not content.strip() and not empty_recovery_used:
                        empty_recovery_used = True
                        self._emit("turn.empty_recovery", {"step": step})
                        ctx.messages.pop()
                        ctx.messages.append({
                            "role": "user",
                            "content": (
                                f"Your previous response had no text. Answer the user's request directly and concisely "
                                f"using the information already gathered above. Do not call tools.\n"
                                f"User request: {prompt[:300]}"
                            ),
                        })
                        try:
                            recovered = self._invoke_model(ctx, allow_tools=False)
                            recovered_text = str(recovered.get("content") or "").strip()
                        except Exception:  # noqa: BLE001
                            recovered_text = ""
                        ctx.messages.pop()
                        if recovered_text:
                            content = recovered_text
                        elif ctx.tool_history:
                            tools_used = ", ".join(dict.fromkeys(str(h.get("tool") or "tool") for h in ctx.tool_history[-6:]))
                            content = (
                                f"I completed {len(ctx.tool_history)} tool call(s) ({tools_used}) "
                                "but the model returned an empty final message. Ask me to summarize or continue if needed."
                            )
                        else:
                            content = "The model returned an empty response. Please retry or rephrase."
                        ctx.messages.append({"role": "assistant", "content": content})
                    if verify_guard is not None and step < total_steps:
                        nudge = verify_guard.maybe_nudge(has_verify_tool=True)
                        if nudge:
                            ctx.messages.append({"role": "user", "content": nudge})
                            self._emit("turn.verify_nudge", {"step": step, "files": list(verify_guard.mutated_files)})
                            continue
                    cp_id = (
                        self._memory.save_checkpoint(self._session_id, {"messages": ctx.messages, "step": step})
                        if self._memory is not None
                        else None
                    )
                    self._emit("turn.complete", {"step": step, "verdict": TurnVerdict.COMPLETE.value})
                    return {
                        "verdict": TurnVerdict.COMPLETE.value,
                        "content": content,
                        "steps": step,
                        "checkpoint_id": cp_id,
                        "messages": ctx.messages,
                    }

                batch_results = self._execute_tool_batch(ctx, tool_calls)
                strategy_hint: str | None = None
                for tc, res in batch_results:
                    tc_id = str(tc.get("id") or f"call_{step}")
                    t_name = self._resolve_tool_name(str(tc.get("name") or ""))
                    t_args = tc.get("arguments", {})
                    if verify_guard is not None:
                        verify_guard.record_tool_result(
                            t_name,
                            t_args if isinstance(t_args, Mapping) else None,
                            ok=res.ok,
                        )
                    hint = convergence.record_tool_result(
                        t_name,
                        t_args if isinstance(t_args, Mapping) else None,
                        ok=res.ok,
                        has_edit_tool=has_edit_tool,
                        has_verify_tool=has_verify_tool,
                    )
                    if hint:
                        strategy_hint = hint
                    ctx.tool_history.append({"tool": t_name, "arguments": t_args, "ok": res.ok})
                    self._emit("tool.result", {"step": step, "tool": t_name, "ok": res.ok})
                    ctx.messages.append({
                        "role": "tool",
                        "name": t_name,
                        "tool_call_id": tc_id,
                        "content": res.output if res.ok else f"ERROR: {res.error}",
                    })

                if self._reliability is not None and self._reliability.check_loop(ctx.tool_history):
                    self._emit("turn.loop_halted", {"step": step})
                    return {
                        "verdict": TurnVerdict.LOOP_HALTED.value,
                        "content": "Halted: repeated tool-call loop detected.",
                        "steps": step,
                        "messages": ctx.messages,
                    }

                if strategy_hint and step < total_steps:
                    self._emit("turn.strategy_shift", {"step": step, "hint": strategy_hint})
                    ctx.messages.append({"role": "user", "content": strategy_hint})

            self._emit("turn.budget_exhausted", {"steps": total_steps})
            content = f"Reached the {total_steps}-step tool limit. The tool results above show what ran."
            if cancel_scope is None or not getattr(cancel_scope, "is_cancelled", False):
                ctx.messages.append({
                    "role": "user",
                    "content": (
                        f"The tool-step limit for this turn has been reached. Give a concise answer or progress update "
                        f"specifically for the current user request ({prompt[:300]}) using the tool results already available. "
                        "State what was verified, anything incomplete or blocked, and the next step. Do not ask for or call tools."
                    ),
                })
                ctx.step = total_steps + 1
                try:
                    summary = self._invoke_model(ctx, allow_tools=False)
                    report = str(summary.get("content") or "").strip()
                    if report and not summary.get("tool_calls"):
                        content = report
                except Exception as exc:
                    self._emit("turn.summary_failed", {"error_type": type(exc).__name__})
                ctx.messages.pop()
            ctx.messages.append({"role": "assistant", "content": content})
            return {
                "verdict": TurnVerdict.BUDGET_EXHAUSTED.value,
                "content": content,
                "steps": total_steps,
                "messages": ctx.messages,
            }
        finally:
            self._middlewares = saved_middlewares
