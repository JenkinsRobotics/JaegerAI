"""Pre-flight context-window guardrail (standalone jaeger-memory module).

Three responsibilities:
  - **Estimate** the assembled prompt's token count from the message list +
    system prompt + tool schemas with live EMA calibration from actual provider
    usage.
  - **Trim** old history until the estimate fits the budget across 3 progressive
    stages: (1) prune old tool-result bodies to one-liners preserving disk
    artifact paths, (2) fold oldest message groups into a single reference digest
    (deterministic or optional LLM summarizer), (3) prune the in-flight turn's
    oldest tool results before refusing with :class:`ContextOverflow`.
  - **Truncate** pathologically huge individual tool results before they land
    in ``messages``, optionally persisting the full body to disk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from jaeger_contracts import Message


@dataclass(frozen=True)
class ContextBudget:
    """Budget parameters for pre-flight context trimming."""

    ctx_window: int = 8192
    reserve_for_completion: int = 1024
    safety_margin: int = 256
    chars_per_token: float = 3.0
    max_tool_result_chars: int = 24_000
    preview_chars: int = 1_500
    artifact_dir: Any = None  # pathlib.Path | None

    @property
    def prompt_budget(self) -> int:
        """Tokens available for the prompt (system + history + tools)."""
        return max(0, self.ctx_window - self.reserve_for_completion - self.safety_margin)


class ContextOverflow(RuntimeError):
    """Raised when the assembled prompt can't fit even after maximum trimming."""

    def __init__(
        self,
        *,
        estimated: int,
        budget: int,
        system_prompt_tokens: int,
        tools_tokens: int,
        latest_user_tokens: int,
        message: str = "",
    ) -> None:
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


@dataclass(frozen=True)
class TrimResult:
    """Result returned by :meth:`ContextGuard.trim_to_fit`."""

    messages: list[Message]
    dropped_count: int
    estimated_tokens: int
    pruned_count: int = 0
    digested: bool = False
    inflight_pruned_count: int = 0


DIGEST_PREFIX = "[EARLIER CONTEXT — REFERENCE ONLY]"
_PRUNE_RESULT_OVER_CHARS = 240
_INFLIGHT_PROTECT_RESULTS = 2
_DIGEST_RESERVE_TOKENS = 450
_DIGEST_MAX_CHARS = 1_200


class ContextGuard:
    """Pre-flight context estimator, trimmer, and oversized-result spiller."""

    def __init__(
        self,
        budget: ContextBudget,
        summarizer: Any = None,
    ) -> None:
        self.budget = budget
        self._ratio: float = budget.chars_per_token or 3.0
        self.summarizer = summarizer

    def estimate_text_tokens(self, text: str) -> int:
        if not text:
            return 0
        ratio = self._ratio or 3.0
        return int(len(text) / ratio) + 1

    def observed_call(
        self,
        prompt_tokens: int,
        messages: list[Message],
        *,
        system_prompt: str,
        tools: Sequence[Any],
    ) -> None:
        """Calibrate the char-per-token ratio from actual provider prompt usage."""
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
                chars += len(
                    json.dumps(
                        [
                            t.to_openai_schema()
                            for t in tools
                            if hasattr(t, "to_openai_schema")
                        ],
                        ensure_ascii=False,
                    )
                )
            except Exception:  # noqa: BLE001
                pass
        if chars < 800:
            return
        raw_ratio = chars / float(prompt_tokens)
        target = max(2.0, min(raw_ratio * 0.9, 5.0))
        self._ratio = 0.5 * self._ratio + 0.5 * target

    def tighten(self, factor: float = 0.85) -> None:
        """Reactive correction after a provider rejects a prompt as too long."""
        self._ratio = max(2.0, self._ratio * factor)

    def estimate_messages_tokens(
        self,
        messages: list[Message],
        *,
        system_prompt: str,
        tools: Sequence[Any],
    ) -> int:
        total = self.estimate_text_tokens(system_prompt or "")
        for m in messages:
            total += self._estimate_message(m)
        if tools:
            schema_blob = json.dumps(
                [
                    t.to_openai_schema()
                    for t in tools
                    if hasattr(t, "to_openai_schema")
                ],
                ensure_ascii=False,
            )
            total += self.estimate_text_tokens(schema_blob)
        return total

    def _estimate_message(self, m: Message) -> int:
        cost = 4
        cost += self.estimate_text_tokens(str(m.get("role", "")))
        content = m.get("content")
        if isinstance(content, str):
            cost += self.estimate_text_tokens(content)
        elif content is not None:
            cost += self.estimate_text_tokens(json.dumps(content, ensure_ascii=False))
        if m.get("provider_state"):
            cost += self.estimate_text_tokens(
                json.dumps(m["provider_state"], ensure_ascii=False, default=str)
            )
        for tc in (m.get("tool_calls") or []):
            cost += self.estimate_text_tokens(str(tc.get("name", "")))
            args = tc.get("arguments") or {}
            if isinstance(args, dict):
                cost += self.estimate_text_tokens(
                    json.dumps(args, ensure_ascii=False)
                )
            else:
                cost += self.estimate_text_tokens(str(args))
        return cost

    def trim_to_fit(
        self,
        messages: list[Message],
        *,
        system_prompt: str,
        tools: Sequence[Any],
    ) -> TrimResult:
        """Make the prompt fit the budget, least-destructively first."""
        budget = self.budget.prompt_budget
        system_tokens = self.estimate_text_tokens(system_prompt or "")
        tools_tokens = self._estimate_tools_tokens(tools)

        keep_start = self._first_kept_index(messages)
        latest_user_tokens = 0
        if keep_start < len(messages):
            latest_user_tokens = sum(
                self._estimate_message(m) for m in messages[keep_start:]
            )

        total = system_tokens + tools_tokens + sum(
            self._estimate_message(m) for m in messages
        )
        if total <= budget:
            return TrimResult(
                messages=list(messages),
                dropped_count=0,
                estimated_tokens=total,
            )

        # Stage 1: prune old tool-result bodies outside the in-flight turn.
        kept, pruned = self._prune_old_tool_results(messages, keep_start)
        estimate = system_tokens + tools_tokens + sum(
            self._estimate_message(m) for m in kept
        )
        if estimate <= budget:
            return TrimResult(
                messages=kept,
                dropped_count=0,
                estimated_tokens=estimate,
                pruned_count=pruned,
            )

        # Stage 2: drop oldest groups into a digest.
        prior_digest = ""
        if (
            kept
            and kept[0].get("role") == "user"
            and str(kept[0].get("content") or "").startswith(DIGEST_PREFIX)
        ):
            prior_digest = str(kept[0].get("content") or "")
            kept = kept[1:]

        floor = len(messages) - keep_start
        dropped_msgs: list[Message] = []
        digest_reserve = min(_DIGEST_RESERVE_TOKENS, max(0, budget // 4))

        digest_affordable = True
        inflight_pruned = 0
        while True:
            estimate = system_tokens + tools_tokens + sum(
                self._estimate_message(m) for m in kept
            )
            reserve = (
                digest_reserve
                if (digest_affordable and (dropped_msgs or prior_digest))
                else 0
            )
            if estimate + reserve <= budget:
                break
            if len(kept) <= floor:
                if estimate <= budget:
                    digest_affordable = False
                    break
                # Stage 3: prune the in-flight turn's oldest tool results.
                if not inflight_pruned:
                    kept, inflight_pruned = self._prune_inflight_tool_results(
                        kept,
                        floor,
                        target_tokens=budget - system_tokens - tools_tokens,
                    )
                    if inflight_pruned:
                        continue
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
                dropped_msgs,
                prior_digest,
                digest_cap,
            )
            if llm_digest:
                digest = llm_digest
            kept = [{"role": "user", "content": digest}, *kept]
            digested = True
            estimate = system_tokens + tools_tokens + sum(
                self._estimate_message(m) for m in kept
            )

        return TrimResult(
            messages=kept,
            dropped_count=len(dropped_msgs),
            estimated_tokens=estimate,
            pruned_count=pruned,
            digested=digested,
            inflight_pruned_count=inflight_pruned,
        )

    def _try_llm_digest(
        self,
        dropped: list[Message],
        prior_digest: str,
        digest_cap: int,
    ) -> str | None:
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
        except Exception:  # noqa: BLE001
            return None
        text = str(out or "").strip()
        if not text:
            return None
        if not text.startswith(DIGEST_PREFIX):
            text = (
                DIGEST_PREFIX
                + " Older turns were compacted. Treat the "
                + "LATEST user message as the source of truth.\n"
                + text
            )
        return text[:digest_cap]

    def _prune_old_tool_results(
        self,
        messages: list[Message],
        keep_start: int,
    ) -> tuple[list[Message], int]:
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

    def _prune_inflight_tool_results(
        self,
        kept: list[Message],
        floor: int,
        *,
        target_tokens: int,
    ) -> tuple[list[Message], int]:
        if floor <= 0:
            return kept, 0
        tail_start = max(0, len(kept) - floor)
        eligible = [
            i
            for i in range(tail_start, len(kept))
            if kept[i].get("role") == "tool"
            and isinstance(kept[i].get("content"), str)
            and len(kept[i]["content"]) > _PRUNE_RESULT_OVER_CHARS
        ]
        if _INFLIGHT_PROTECT_RESULTS:
            eligible = eligible[:-_INFLIGHT_PROTECT_RESULTS]
        if not eligible:
            return kept, 0
        out = list(kept)
        estimate = sum(self._estimate_message(m) for m in out)
        pruned = 0
        for i in eligible:
            if estimate <= target_tokens:
                break
            original = out[i]
            stub = {
                **original,
                "content": _result_stub(
                    original.get("name") or "tool",
                    original["content"],
                ),
            }
            estimate -= self._estimate_message(original)
            estimate += self._estimate_message(stub)
            out[i] = stub
            pruned += 1
        return (out, pruned) if pruned else (kept, 0)

    @staticmethod
    def _head_group_size(messages: list[Message]) -> int:
        if not messages:
            return 0
        head = messages[0]
        if head.get("role") != "assistant":
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
            break
        return size

    def _first_kept_index(self, messages: list[Message]) -> int:
        last_user = -1
        for i, m in enumerate(messages):
            if m.get("role") == "user":
                last_user = i
        if last_user < 0:
            return max(0, len(messages) - 1)
        return last_user

    def _estimate_tools_tokens(self, tools: Sequence[Any]) -> int:
        if not tools:
            return 0
        try:
            schema_blob = json.dumps(
                [
                    t.to_openai_schema()
                    for t in tools
                    if hasattr(t, "to_openai_schema")
                ],
                ensure_ascii=False,
            )
        except Exception:  # noqa: BLE001
            return 0
        return self.estimate_text_tokens(schema_blob)

    def truncate_oversized_result(self, result: Any) -> tuple[Any, bool]:
        """Replace oversized tool results with a preview + optional disk artifact path."""
        cap = self.budget.max_tool_result_chars
        if cap <= 0:
            return result, False

        serialised = self._serialise_result(result)
        if len(serialised) <= cap:
            return result, False

        file_result = (
            isinstance(result, dict)
            and result.get("read") is True
            and isinstance(result.get("content"), str)
        )
        artifact_body = result["content"] if file_result else serialised
        preview = artifact_body[: self.budget.preview_chars]
        artifact_path = self._persist_artifact(artifact_body)
        marker_msg = (
            f"\n\n[result truncated — original was {len(serialised)} chars "
            f"({len(serialised) // max(1, int(self.budget.chars_per_token))} "
            f"tokens approx); first {self.budget.preview_chars} chars kept"
            + (f"; full result saved to {artifact_path}" if artifact_path else "")
            + "]"
        )
        if isinstance(result, dict):
            marker_dict: dict[str, Any] = {
                "_truncated": True,
                "original_chars": len(serialised),
                "preview": preview,
            }
            if file_result:
                for key in (
                    "read",
                    "path",
                    "offset",
                    "column",
                    "total_lines",
                    "truncated",
                    "next_offset",
                    "next_column",
                ):
                    if key in result:
                        marker_dict[key] = result[key]
            if artifact_path:
                marker_dict["artifact_path"] = str(artifact_path)
                marker_dict["hint"] = (
                    "Full result persisted — call read_file with the "
                    "artifact_path and a small limit (e.g. 40 lines). "
                    "Page using next_offset/next_column; do not read the "
                    "whole artifact repeatedly."
                )
            return marker_dict, True
        return preview + marker_msg, True

    def _persist_artifact(self, serialised: str) -> Any:
        out_dir = self.budget.artifact_dir
        if out_dir is None:
            return None
        try:
            import time as _t
            import uuid

            d = Path(out_dir)
            d.mkdir(parents=True, exist_ok=True)
            ts = _t.strftime("%Y%m%d-%H%M%S")
            stub = uuid.uuid4().hex[:8]
            try:
                json.loads(serialised)
                suffix = ".json"
            except (ValueError, TypeError):
                suffix = ".txt"
            path = d / f"{ts}_{stub}{suffix}"
            path.write_text(serialised, encoding="utf-8")
            return path
        except Exception:  # noqa: BLE001
            return None

    def _serialise_result(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            return str(result)


def _result_stub(tool_name: str, body: str) -> str:
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
        DIGEST_PREFIX
        + " Older turns were compacted to fit the "
        + "context window. This is a lossy digest — treat the LATEST "
        + "user message as the source of truth and do not re-answer "
        + "anything already settled here.",
    ]
    if prior_digest:
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
    """How many leading messages must drop together to keep tool calls paired."""
    return ContextGuard._head_group_size(messages)


__all__ = [
    "ContextBudget",
    "ContextGuard",
    "ContextOverflow",
    "DIGEST_PREFIX",
    "TrimResult",
    "oldest_group_size",
]
