"""Pre-flight context-window guardrail.

JROS's reactive guardrail (:mod:`jaeger_os.core.runtime.cloud_errors`)
catches "Requested tokens exceed context window" *after* the server
hard-fails. This module catches it *before* — the next turn won't be
sent if it can't fit.

Three responsibilities:

  - **Estimate** the assembled prompt's token count from the message
    list + system prompt + tool schemas. Char-based heuristic by
    default (no tokenizer dep); a real tokenizer can plug in later.

  - **Trim** old history until the estimate fits the budget. Preserves
    the system prompt, the most recent user message, and any
    assistant/tool messages from the in-flight turn.

  - **Truncate** an individual tool result that's pathologically huge
    (a multi-megabyte ``run_shell`` dump, a screenshot, etc.) before
    it lands in ``messages``. Replaces with a preview + size marker.

When even maximum trimming doesn't fit, raise :class:`ContextOverflow`
so the caller can render an actionable message instead of forwarding
the server's hard error.

Design rationale
----------------
**Why a char-heuristic, not tiktoken?** Zero deps + works for every
backend. A real tokenizer adds 5-50 MB of vocab files and only helps
when the model has a published tokenizer (gemma, qwen, llama all
differ). The 3.0 chars/token default *overestimates* — better to trim
one turn too many than to overflow by one.

**Why a separate module, not a method on the agent?** Tests need to
exercise the trim logic without standing up an agent. The agent calls
in via :meth:`ContextGuard.trim_to_fit` and :meth:`truncate_oversized_result`;
that's the whole surface.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from jaeger_os.agent.schemas.message_types import Message
from jaeger_os.agent.schemas.tool_schema import ToolDef


# ── budget ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ContextBudget:
    """The numbers we trim against. Defaults match the framework's
    default ``config.model.ctx`` of 8192, with reasonable reserves.

    Bigger ``reserve_for_completion`` = answers can be longer, but the
    prompt has less room. The right value is workload-dependent —
    chat-heavy users want more answer room, agent-heavy users want more
    prompt room. 1024 is a middle ground that lets a typical "summarise
    this in one paragraph" call complete without truncation."""

    ctx_window: int = 8192
    reserve_for_completion: int = 1024
    safety_margin: int = 256
    # Conservative bias — real ratio is ~3.5–4.0 for English / code.
    # 3.0 means we'll *overestimate* by ~15-25%, which is what we want.
    chars_per_token: float = 3.0
    # Per-tool-result hard cap (in chars of the JSON serialisation).
    # 24K chars ≈ 8K tokens at 3.0 — a single result that big eats
    # half the budget, which is almost always wrong.
    max_tool_result_chars: int = 24_000
    # How much of the original result body to keep when truncating.
    preview_chars: int = 1_500
    # When set, oversized tool results are PERSISTED to a file under
    # this directory (typically ``<instance>/logs/tool_results/``) and
    # the model gets back a preview + the on-disk path so it can read
    # more if needed. ``None`` keeps the legacy truncate-only path
    # (default for unit tests + bench code that doesn't have a layout
    # bound). The agent wires this from ``layout.logs_dir`` at
    # construction time when the layout is available.
    artifact_dir: Any = None    # pathlib.Path | None

    @property
    def prompt_budget(self) -> int:
        """Tokens available for the prompt (system + history + tools)."""
        return max(0, self.ctx_window - self.reserve_for_completion - self.safety_margin)


# ── exception ──────────────────────────────────────────────────────


class ContextOverflow(RuntimeError):
    """Raised when the assembled prompt can't fit in the budget even
    after every droppable message is dropped. Carries enough detail for
    the renderer to surface 'budget=X, needed=Y' instead of just
    forwarding the server's terse error."""

    def __init__(self, *, estimated: int, budget: int,
                 system_prompt_tokens: int, tools_tokens: int,
                 latest_user_tokens: int, message: str = "") -> None:
        self.estimated = estimated
        self.budget = budget
        self.system_prompt_tokens = system_prompt_tokens
        self.tools_tokens = tools_tokens
        self.latest_user_tokens = latest_user_tokens
        text = message or (
            f"context overflow: prompt needs ~{estimated} tokens, "
            f"budget is {budget} (system={system_prompt_tokens}, "
            f"tools={tools_tokens}, latest user msg={latest_user_tokens})"
        )
        super().__init__(text)


# ── trim result ────────────────────────────────────────────────────


@dataclass(frozen=True)
class TrimResult:
    """What :meth:`ContextGuard.trim_to_fit` produces."""
    messages: list[Message]
    dropped_count: int
    estimated_tokens: int


# ── the guard ──────────────────────────────────────────────────────


class ContextGuard:
    """Stateless helper around a :class:`ContextBudget`. Construct once
    per :class:`JaegerAgent`; methods are pure-of-side-effects on the
    inputs (messages are not mutated in place)."""

    def __init__(self, budget: ContextBudget) -> None:
        self.budget = budget

    # ── estimator ──────────────────────────────────────────────────

    def estimate_text_tokens(self, text: str) -> int:
        """Char-based estimate. Cheap (no tokenizer load), conservative
        (real tokenizers give fewer tokens than this for English)."""
        if not text:
            return 0
        ratio = self.budget.chars_per_token or 3.0
        # +1 captures the per-message overhead a real chat-template
        # tokeniser adds (``<|im_start|>...``, etc.). One token per
        # text-bearing chunk is a fine first approximation.
        return int(len(text) / ratio) + 1

    def estimate_messages_tokens(
        self,
        messages: list[Message],
        *,
        system_prompt: str,
        tools: list[ToolDef],
    ) -> int:
        """Sum the contribution of every wire-carried piece: the system
        prompt, each message body (including tool call args + tool
        return content), and the tool-schema JSON the server sees."""
        total = self.estimate_text_tokens(system_prompt or "")
        for m in messages:
            total += self._estimate_message(m)
        # Tool schemas — JSON-serialise once, count chars.
        if tools:
            schema_blob = json.dumps(
                [t.to_openai_schema() for t in tools if hasattr(t, "to_openai_schema")],
                ensure_ascii=False,
            )
            total += self.estimate_text_tokens(schema_blob)
        return total

    def _estimate_message(self, m: Message) -> int:
        """One message's tokens — role + content + (tool calls or tool
        return) + a small per-message header overhead."""
        # ~4 tokens of header per message (role tag, newlines, etc.).
        # Anthropic / OpenAI / Hermes all add some framing.
        cost = 4
        cost += self.estimate_text_tokens(str(m.get("role", "")))
        content = m.get("content")
        if isinstance(content, str):
            cost += self.estimate_text_tokens(content)
        elif content is not None:
            cost += self.estimate_text_tokens(json.dumps(content, ensure_ascii=False))
        # Tool calls on assistant messages.
        for tc in (m.get("tool_calls") or []):
            cost += self.estimate_text_tokens(str(tc.get("name", "")))
            args = tc.get("arguments") or {}
            if isinstance(args, dict):
                cost += self.estimate_text_tokens(
                    json.dumps(args, ensure_ascii=False)
                )
            else:
                cost += self.estimate_text_tokens(str(args))
        # Tool return content is already in ``content`` above when the
        # role is "tool"; nothing extra to count.
        return cost

    # ── trim ───────────────────────────────────────────────────────

    def trim_to_fit(
        self,
        messages: list[Message],
        *,
        system_prompt: str,
        tools: list[ToolDef],
    ) -> TrimResult:
        """Drop oldest non-system messages until the estimate fits the
        budget. Preserves the most recent user message and any
        assistant/tool chain that comes after it (the in-flight turn).

        Raises :class:`ContextOverflow` if even the keep-set is too big.
        """
        budget = self.budget.prompt_budget
        system_tokens = self.estimate_text_tokens(system_prompt or "")
        tools_tokens = self._estimate_tools_tokens(tools)

        keep_start = self._first_kept_index(messages)
        latest_user_tokens = 0
        if keep_start < len(messages):
            latest_user_tokens = sum(
                self._estimate_message(m) for m in messages[keep_start:]
            )

        # Fast path — already fits, no trimming needed.
        total = system_tokens + tools_tokens + sum(
            self._estimate_message(m) for m in messages
        )
        if total <= budget:
            return TrimResult(messages=list(messages),
                              dropped_count=0,
                              estimated_tokens=total)

        # Drop droppable messages from the head until we fit or run out.
        # Drop in *groups* so an assistant-with-tool_calls and its
        # matching tool-result messages are removed together. Orphaning
        # a tool result (assistant gone but tool message remains) makes
        # OpenAI's API 400 and confuses Hermes-XML parsers; orphaning
        # an assistant tool_calls (tool results gone but assistant
        # references their ids) wastes tokens on dangling call ids the
        # model will retry.
        kept: list[Message] = list(messages)
        dropped = 0
        floor = len(messages) - keep_start  # never trim below this length

        while True:
            estimate = system_tokens + tools_tokens + sum(
                self._estimate_message(m) for m in kept
            )
            if estimate <= budget:
                return TrimResult(messages=kept,
                                  dropped_count=dropped,
                                  estimated_tokens=estimate)
            # Hit the undroppable floor — even with everything droppable
            # removed the prompt won't fit. Surface a typed error.
            if len(kept) <= floor:
                raise ContextOverflow(
                    estimated=estimate,
                    budget=budget,
                    system_prompt_tokens=system_tokens,
                    tools_tokens=tools_tokens,
                    latest_user_tokens=latest_user_tokens,
                )
            # Compute the size of the next "group" at the head — usually
            # 1 message, but an assistant with tool_calls pulls in
            # subsequent tool messages with matching call ids.
            group_n = self._head_group_size(kept)
            # Don't cross the floor; cap the drop at what's safely
            # droppable.
            group_n = min(group_n, len(kept) - floor)
            if group_n <= 0:
                # Defensive — shouldn't happen given the floor check
                # above, but bail rather than spin.
                raise ContextOverflow(
                    estimated=estimate,
                    budget=budget,
                    system_prompt_tokens=system_tokens,
                    tools_tokens=tools_tokens,
                    latest_user_tokens=latest_user_tokens,
                )
            kept = kept[group_n:]
            dropped += group_n

    @staticmethod
    def _head_group_size(messages: list[Message]) -> int:
        """How many messages at the head must drop together to keep
        assistant tool_calls paired with their matching tool results.

        Group rules:
          • An assistant message with ``tool_calls`` pulls in every
            following ``role="tool"`` message whose ``tool_call_id``
            matches one of those calls.
          • A bare ``tool`` message at the head — orphaned from a prior
            trim or a corrupted history — is one group on its own; the
            adapter would error on it anyway, so dropping it cleans up.
          • Anything else (system/user/assistant-without-tool_calls)
            drops as a single message.
        """
        if not messages:
            return 0
        head = messages[0]
        head_role = head.get("role")
        if head_role != "assistant":
            return 1
        head_tcs = head.get("tool_calls") or []
        if not head_tcs:
            return 1
        wanted_ids = {tc.get("id") for tc in head_tcs if tc.get("id")}
        size = 1
        for m in messages[1:]:
            if m.get("role") != "tool":
                break
            if m.get("tool_call_id") in wanted_ids:
                size += 1
                continue
            # A tool message that doesn't belong to *this* assistant's
            # call set — stop the group here; the next iteration will
            # treat it as its own head.
            break
        return size

    def _first_kept_index(self, messages: list[Message]) -> int:
        """Index of the message that begins the *undroppable* tail —
        the latest user message and anything after it (the in-flight
        turn). Falls back to the last message if no user role is found."""
        last_user = -1
        for i, m in enumerate(messages):
            if m.get("role") == "user":
                last_user = i
        if last_user < 0:
            return max(0, len(messages) - 1)
        return last_user

    def _estimate_tools_tokens(self, tools: list[ToolDef]) -> int:
        if not tools:
            return 0
        try:
            schema_blob = json.dumps(
                [t.to_openai_schema() for t in tools if hasattr(t, "to_openai_schema")],
                ensure_ascii=False,
            )
        except Exception:  # noqa: BLE001
            return 0
        return self.estimate_text_tokens(schema_blob)

    # ── per-tool truncate ──────────────────────────────────────────

    def truncate_oversized_result(self, result: Any) -> tuple[Any, bool]:
        """If ``result`` is large enough to dominate the next turn's
        context, replace it with a preview + (when ``artifact_dir`` is
        set) an on-disk path the model can read for the rest.

        Two modes, picked by ``budget.artifact_dir``:

          - **artifact_dir set** — write the full result to a file
            under that directory and hand back a marker dict pointing
            at it::

                {"_truncated": True, "original_chars": N,
                 "preview": "first 1.5K chars",
                 "artifact_path": "<instance>/logs/tool_results/<id>.json"}

            The model can ``read_file(artifact_path)`` if it needs
            more than the preview. This is the right shape for
            embodied work — sensor dumps, screenshots, big ``run_shell``
            captures, browser HTML — where blunt truncation loses
            information that may matter later in the turn.

          - **artifact_dir is None** (legacy fallback) — emit a
            preview + size marker only. Used by tests / bench harness
            where no instance layout is bound.

        Returns ``(possibly_modified_result, was_truncated)``.

        ``max_tool_result_chars=0`` disables truncation entirely —
        caller passes results through verbatim. Useful for benchmarks
        that need full fidelity."""
        cap = self.budget.max_tool_result_chars
        if cap <= 0:
            return result, False

        serialised = self._serialise_result(result)
        if len(serialised) <= cap:
            return result, False

        preview = serialised[: self.budget.preview_chars]
        artifact_path = self._persist_artifact(serialised)
        marker_msg = (
            f"\n\n[result truncated — original was {len(serialised)} chars "
            f"({len(serialised) // max(1, int(self.budget.chars_per_token))} "
            f"tokens approx); first {self.budget.preview_chars} chars kept"
            + (f"; full result saved to {artifact_path}" if artifact_path else "")
            + "]"
        )
        # If the original was a dict-shape, hand back a dict marker so
        # the model can still ``[key]``-into it without crashing.
        if isinstance(result, dict):
            marker_dict: dict[str, Any] = {
                "_truncated": True,
                "original_chars": len(serialised),
                "preview": preview,
            }
            if artifact_path:
                marker_dict["artifact_path"] = str(artifact_path)
                marker_dict["hint"] = (
                    "Full result persisted — call read_file with the "
                    "artifact_path if you need the bytes the preview "
                    "cut off."
                )
            return marker_dict, True
        return preview + marker_msg, True

    def _persist_artifact(self, serialised: str) -> Any:
        """Write an oversized result body to ``artifact_dir`` and
        return its absolute path. Returns ``None`` when no directory
        is configured or the write fails. Best-effort: a failure here
        falls back to the preview-only path; we never block a tool
        call over an audit/log-write hiccup."""
        out_dir = self.budget.artifact_dir
        if out_dir is None:
            return None
        try:
            import pathlib, uuid, time as _t
            d = pathlib.Path(out_dir)
            d.mkdir(parents=True, exist_ok=True)
            # Filename is timestamp + short uuid — easy for the model
            # (and the operator) to skim recent artifacts in order.
            ts = _t.strftime("%Y%m%d-%H%M%S")
            stub = uuid.uuid4().hex[:8]
            # If the body is valid JSON we keep the .json extension so
            # editors render it nicely; otherwise treat as plain text.
            try:
                import json as _json
                _json.loads(serialised)
                suffix = ".json"
            except (ValueError, TypeError):
                suffix = ".txt"
            path = d / f"{ts}_{stub}{suffix}"
            path.write_text(serialised, encoding="utf-8")
            return path
        except Exception:  # noqa: BLE001 — never break dispatch over an artifact write
            return None

    def _serialise_result(self, result: Any) -> str:
        """Best-effort 'how big would this be on the wire?' — JSON for
        dicts/lists, str() for everything else. Used only for the
        size check; the original value is what the caller hands back."""
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            return str(result)


__all__ = [
    "ContextBudget",
    "ContextGuard",
    "ContextOverflow",
    "TrimResult",
]
