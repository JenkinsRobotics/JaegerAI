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
from dataclasses import dataclass
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
    # How many old tool results had their bodies pruned to one-liners
    # (stage 1) before any whole-message drop was considered.
    pruned_count: int = 0
    # True when dropped turns were folded into a digest message rather
    # than silently deleted (stage 2).
    digested: bool = False


# ── the guard ──────────────────────────────────────────────────────


# Marker prefix for the stage-2 digest message. Detection on
# re-compaction keys off this exact prefix, so older digests are folded
# into the new one instead of stacking up.
DIGEST_PREFIX = "[EARLIER CONTEXT — REFERENCE ONLY]"

# Tool-result bodies above this many chars are eligible for stage-1
# pruning once their turn leaves the protected tail.
_PRUNE_RESULT_OVER_CHARS = 240

# Token reserve subtracted from the budget while dropping groups, so
# the digest message that replaces them always fits.
_DIGEST_RESERVE_TOKENS = 450
_DIGEST_MAX_CHARS = 1_200


class ContextGuard:
    """Helper around a :class:`ContextBudget`. Construct once per
    :class:`JaegerAgent`; methods never mutate the input message list
    (replaced messages are fresh dicts). Holds two pieces of per-agent
    state: the calibrated chars-per-token ratio (see
    :meth:`observed_call`) and nothing else."""

    def __init__(
        self,
        budget: ContextBudget,
        summarizer: Any = None,
    ) -> None:
        self.budget = budget
        # Live chars-per-token ratio. Starts at the configured
        # conservative default; tightened toward the model's REAL
        # tokenizer by ``observed_call`` as actual usage arrives.
        self._ratio: float = budget.chars_per_token or 3.0
        # Optional LLM digest: a ``Callable[[str], str]`` that turns a
        # serialized span of dropped turns into a dense summary. When
        # set, stage-2 compaction prefers it over the deterministic
        # digest, falling back on ANY failure. Costs a model call
        # (seconds) — wire it ONLY where latency is free (deep think),
        # never on the voice path.
        self.summarizer = summarizer

    # ── estimator ──────────────────────────────────────────────────

    def estimate_text_tokens(self, text: str) -> int:
        """Char-based estimate. Cheap (no tokenizer load), conservative
        (real tokenizers give fewer tokens than this for English)."""
        if not text:
            return 0
        ratio = self._ratio or 3.0
        # +1 captures the per-message overhead a real chat-template
        # tokeniser adds (``<|im_start|>...``, etc.). One token per
        # text-bearing chunk is a fine first approximation.
        return int(len(text) / ratio) + 1

    def observed_call(
        self,
        prompt_tokens: int,
        messages: list[Message],
        *,
        system_prompt: str,
        tools: list[ToolDef],
    ) -> None:
        """Calibrate the estimator from REAL provider usage.

        The char heuristic deliberately overestimates (~15-25%) so we
        trim early rather than overflow. With actual ``prompt_tokens``
        from the API response we can measure the model's true
        chars-per-token and shrink that overestimate — fewer needless
        trims and compactions per session — while keeping a 10%%
        conservative bias and hard clamps so one weird payload can't
        swing the estimator into under-counting. EMA-smoothed; cheap
        (one char-count walk per model call)."""
        if not prompt_tokens or prompt_tokens <= 0:
            return
        chars = len(system_prompt or "")
        for m in messages:
            content = m.get("content")
            if isinstance(content, str):
                chars += len(content)
            for tc in (m.get("tool_calls") or []):
                args = tc.get("arguments")
                chars += len(str(tc.get("name") or "")) + len(str(args or ""))
        if tools:
            try:
                chars += len(json.dumps(
                    [t.to_openai_schema() for t in tools
                     if hasattr(t, "to_openai_schema")],
                    ensure_ascii=False,
                ))
            except Exception:  # noqa: BLE001
                pass
        if chars < 800:
            return  # too small a sample to calibrate from
        raw_ratio = chars / float(prompt_tokens)
        # 10% conservative discount + hard clamps, then smooth.
        target = max(2.0, min(raw_ratio * 0.9, 5.0))
        self._ratio = 0.5 * self._ratio + 0.5 * target

    def tighten(self, factor: float = 0.85) -> None:
        """Reactive correction: a SERVER just rejected a prompt this
        estimator thought fit, so the ratio was too optimistic. Shrink
        it (more chars-per-token pessimism → bigger token estimates →
        the next trim drops more). :meth:`observed_call` relaxes it
        back toward reality from subsequent real usage, so one bad
        rejection doesn't permanently over-trim."""
        self._ratio = max(2.0, self._ratio * factor)

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
        """Make the prompt fit the budget, least-destructively first.

        Three stages (Hermes ``context_compressor`` pattern, sized for
        a local-first agent — every stage is deterministic, no LLM
        call, sub-millisecond):

          1. **Prune** — old tool-result bodies (outside the in-flight
             turn) are replaced with one-line stubs. When the result
             was spilled to disk by :meth:`truncate_oversized_result`,
             the stub keeps the artifact path so the model can still
             ``read_file`` it. Usually this alone fits the prompt and
             NO conversation turns are lost.
          2. **Digest + drop** — oldest message groups are dropped as
             before, but folded into one ``DIGEST_PREFIX`` reference
             message (user asks, tools used, errors seen) instead of
             vanishing. A previous digest is merged, never stacked.
          3. **Refuse** — :class:`ContextOverflow` when even that
             can't fit.

        Preserves the most recent user message and everything after it
        (the in-flight turn) verbatim, always.
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

        # ── stage 1: prune old tool-result bodies ──────────────────
        kept, pruned = self._prune_old_tool_results(messages, keep_start)
        estimate = system_tokens + tools_tokens + sum(
            self._estimate_message(m) for m in kept
        )
        if estimate <= budget:
            return TrimResult(messages=kept,
                              dropped_count=0,
                              estimated_tokens=estimate,
                              pruned_count=pruned)

        # ── stage 2: drop oldest groups into a digest ──────────────
        # Drop in *groups* so an assistant-with-tool_calls and its
        # matching tool-result messages are removed together. Orphaning
        # either side makes OpenAI's API 400 and confuses Hermes-XML
        # parsers. An existing digest at the head is folded into the
        # new one rather than dropped or duplicated. While dropping,
        # reserve room for the digest message itself.
        prior_digest = ""
        if (
            kept
            and kept[0].get("role") == "user"
            and str(kept[0].get("content") or "").startswith(DIGEST_PREFIX)
        ):
            prior_digest = str(kept[0].get("content") or "")
            kept = kept[1:]

        floor = len(messages) - keep_start  # never trim below this length
        dropped_msgs: list[Message] = []
        # Reserve room for the digest message itself while dropping —
        # scaled to the budget so tiny windows (unit tests, severely
        # constrained models) still resolve instead of dropping to the
        # floor chasing an unaffordable reserve.
        digest_reserve = min(_DIGEST_RESERVE_TOKENS, max(0, budget // 4))

        digest_affordable = True
        while True:
            estimate = system_tokens + tools_tokens + sum(
                self._estimate_message(m) for m in kept
            )
            reserve = digest_reserve if (
                digest_affordable and (dropped_msgs or prior_digest)
            ) else 0
            if estimate + reserve <= budget:
                break
            # Hit the undroppable floor. If the prompt fits WITHOUT the
            # digest reserve, the window is simply too tight to afford
            # a digest — fall back to plain dropping rather than
            # refusing a prompt that would have fit before. Otherwise
            # surface the typed error.
            if len(kept) <= floor:
                if estimate <= budget:
                    digest_affordable = False
                    break
                raise ContextOverflow(
                    estimated=estimate,
                    budget=budget,
                    system_prompt_tokens=system_tokens,
                    tools_tokens=tools_tokens,
                    latest_user_tokens=latest_user_tokens,
                )
            group_n = self._head_group_size(kept)
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
            dropped_msgs.extend(kept[:group_n])
            kept = kept[group_n:]

        digested = False
        digest_cap = min(_DIGEST_MAX_CHARS, int(digest_reserve * self._ratio))
        if (dropped_msgs or prior_digest) and digest_affordable and digest_cap >= 80:
            digest = _build_digest(dropped_msgs, prior_digest)[:digest_cap]
            llm_digest = self._try_llm_digest(
                dropped_msgs, prior_digest, digest_cap,
            )
            if llm_digest:
                digest = llm_digest
            kept = [{"role": "user", "content": digest}, *kept]
            digested = True
            estimate = system_tokens + tools_tokens + sum(
                self._estimate_message(m) for m in kept
            )

        return TrimResult(messages=kept,
                          dropped_count=len(dropped_msgs),
                          estimated_tokens=estimate,
                          pruned_count=pruned,
                          digested=digested)

    def _try_llm_digest(
        self,
        dropped: list[Message],
        prior_digest: str,
        digest_cap: int,
    ) -> str | None:
        """LLM-written digest of the dropped span, when a summarizer is
        wired (deep think only — costs seconds). Returns ``None`` on
        any failure so the deterministic digest stands in; compaction
        must never break a turn over a summarizer hiccup."""
        if self.summarizer is None or not dropped:
            return None
        lines: list[str] = []
        if prior_digest:
            body = prior_digest.split("\n", 1)[-1].strip()
            if body:
                lines.append(f"[EARLIER DIGEST]: {body[:600]}")
        for msg in dropped:
            role = str(msg.get("role") or "?").upper()
            content = msg.get("content")
            text = content if isinstance(content, str) else ""
            for tc in (msg.get("tool_calls") or []):
                text += f" [called {tc.get('name')}({tc.get('arguments')})]"
            text = " ".join(text.split())[:500]
            if text:
                lines.append(f"{role}: {text}")
        serialized = "\n".join(lines)[:6_000]
        prompt = (
            "Compress this span of an agent conversation into a dense "
            "factual digest (max ~150 words): the user's asks, what was "
            "done, key results/decisions, errors hit, anything still "
            "open. No preamble, no commentary — output ONLY the "
            "digest.\n\n" + serialized
        )
        try:
            out = self.summarizer(prompt)
        except Exception:  # noqa: BLE001 — fall back to the deterministic digest
            return None
        text = str(out or "").strip()
        if not text:
            return None
        if not text.startswith(DIGEST_PREFIX):
            text = (
                DIGEST_PREFIX + " Older turns were compacted. Treat the "
                "LATEST user message as the source of truth.\n" + text
            )
        return text[:digest_cap]

    def _prune_old_tool_results(
        self, messages: list[Message], keep_start: int,
    ) -> tuple[list[Message], int]:
        """Stage 1: replace large tool-result bodies OUTSIDE the
        in-flight turn with one-line stubs. Returns ``(new_list,
        pruned_count)``; input list and its dicts are not mutated."""
        out: list[Message] = []
        pruned = 0
        for i, msg in enumerate(messages):
            if i >= keep_start or msg.get("role") != "tool":
                out.append(msg)
                continue
            body = msg.get("content")
            if not isinstance(body, str) or len(body) <= _PRUNE_RESULT_OVER_CHARS:
                out.append(msg)
                continue
            stub = _result_stub(msg.get("name") or "tool", body)
            out.append({**msg, "content": stub})
            pruned += 1
        return out, pruned

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
            import pathlib
            import time as _t
            import uuid
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


def _result_stub(tool_name: str, body: str) -> str:
    """One-line replacement for a pruned tool-result body. Keeps the
    artifact path when the result was spilled to disk, so the model
    can still ``read_file`` the full payload later — the reference
    survives even though the bytes leave the window."""
    artifact = ""
    error_line = ""
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            if parsed.get("artifact_path"):
                artifact = f"; full result on disk: {parsed['artifact_path']}"
            if parsed.get("ok") is False and parsed.get("error"):
                error_line = (
                    f"; FAILED: {str(parsed['error']).splitlines()[0][:120]}"
                )
    except (ValueError, TypeError):
        pass
    return (
        f"[{tool_name} result pruned for context — was {len(body)} chars"
        f"{error_line}{artifact}]"
    )


def _build_digest(dropped: list[Message], prior_digest: str) -> str:
    """Deterministic digest of dropped turns — no LLM call, so it adds
    zero latency to a voice turn. Captures the bones (user asks, tools
    used, errors hit) so the model retains orientation instead of
    total amnesia about the dropped span. A previous digest's body is
    carried forward in compressed form, never stacked verbatim."""
    user_asks: list[str] = []
    tool_counts: dict[str, int] = {}
    errors: list[str] = []
    assistant_said = 0
    last_assistant = ""

    for msg in dropped:
        role = msg.get("role")
        content = msg.get("content")
        text = content if isinstance(content, str) else ""
        if role == "user":
            line = " ".join(text.split())[:110]
            if line and not line.startswith(DIGEST_PREFIX):
                user_asks.append(line)
        elif role == "assistant":
            if text.strip():
                assistant_said += 1
                last_assistant = " ".join(text.split())[:110]
            for tc in (msg.get("tool_calls") or []):
                name = tc.get("name") or "?"
                tool_counts[name] = tool_counts.get(name, 0) + 1
        elif role == "tool":
            if "FAILED:" in text or '"ok": false' in text.lower():
                errors.append(" ".join(text.split())[:110])

    parts: list[str] = [
        DIGEST_PREFIX + " Older turns were compacted to fit the "
        "context window. This is a lossy digest — treat the LATEST "
        "user message as the source of truth and do not re-answer "
        "anything already settled here.",
    ]
    if prior_digest:
        # Carry the previous digest's body (sans its own preamble),
        # squeezed — repeated compactions converge instead of growing.
        body = prior_digest.split("\n", 1)[-1].strip()
        if body:
            parts.append("Earlier still: " + " ".join(body.split())[:300])
    if user_asks:
        parts.append("User asked: " + " | ".join(user_asks[-6:]))
    if tool_counts:
        tools_line = ", ".join(
            f"{name}×{n}" if n > 1 else name
            for name, n in sorted(tool_counts.items())
        )
        parts.append(f"Tools used: {tools_line}")
    if assistant_said:
        parts.append(
            f"Assistant replied {assistant_said}×; most recent gist: "
            f"{last_assistant}"
        )
    if errors:
        parts.append("Errors hit: " + " | ".join(errors[-3:]))

    digest = "\n".join(parts)
    return digest[:_DIGEST_MAX_CHARS]


def oldest_group_size(messages: list[Message]) -> int:
    """How many messages at the head of ``messages`` must be dropped
    TOGETHER to keep the transcript well-formed — an assistant message
    with ``tool_calls`` pulls its matching tool results along.

    Public wrapper over the trim rule so history clamps outside this
    module (the per-session clamp in ``main.py``) can't orphan a tool
    result from its call: an orphaned pair makes OpenAI / Anthropic
    400 on every subsequent request."""
    return ContextGuard._head_group_size(messages)


__all__ = [
    "ContextBudget",
    "ContextGuard",
    "ContextOverflow",
    "DIGEST_PREFIX",
    "TrimResult",
    "oldest_group_size",
]
