"""Reliability engine implementing ReliabilityPort.

Synthesizes:
- hermes-agent (`error_classifier.py`, `credential_pool.py`, `tool_guardrails.py`):
  typed FailoverReason + multi-key cooldown rotation + identical-call loop checks.
- ag2 (`llm_retry.py`) + cline (`retry-empty-response.ts`):
  zero-event-safe streaming retries (never retry once chunks were published).
- opencode (`tool-input-repair.ts`) + JaegerAI (`tool_repair.py`):
  deterministic JSON/fence/Python-literal repair + JSON-Schema type coercion +
  hallucinated tool-name aliasing.
- AutoGPT MIT (`watchdog.py`): stuck-loop escalation signal (`escalate_model`).
"""

from __future__ import annotations

import ast
import json
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterator, Mapping, Sequence


class FailoverReason(str, Enum):
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    QUOTA = "quota"
    NOT_FOUND = "not_found"
    CONTEXT_OVERFLOW = "context_overflow"
    TRANSIENT = "transient"
    EMPTY_RESPONSE = "empty_response"
    FATAL = "fatal"


_QUOTA_MARKERS = (
    "insufficient_quota",
    "insufficient quota",
    "exceeded your current quota",
    "out of credits",
    "billing",
    "payment required",
)


def _http_status(error: BaseException) -> int | None:
    for attr in ("status_code", "status", "http_status", "code"):
        val = getattr(error, attr, None)
        if isinstance(val, int) and 100 <= val <= 599:
            return val
    resp = getattr(error, "response", None)
    if resp is not None:
        val = getattr(resp, "status_code", None)
        if isinstance(val, int) and 100 <= val <= 599:
            return val
    return None


def _error_text(error: BaseException) -> str:
    parts = [type(error).__name__, str(error)]
    for attr in ("code", "type"):
        val = getattr(error, attr, None)
        if isinstance(val, str):
            parts.append(val)
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        inner = body.get("error") if isinstance(body.get("error"), dict) else body
        if isinstance(inner, dict):
            for key in ("code", "type", "message"):
                val = inner.get(key)
                if isinstance(val, str):
                    parts.append(val)
    return " ".join(parts).lower()


def classify_error(error: BaseException) -> str:
    """Classify provider/runtime exceptions into actionable FailoverReason values."""
    name = type(error).__name__.lower()
    status = _http_status(error)
    msg = _error_text(error)

    if status in (401, 403) or "authenticat" in name or "permissiondenied" in name:
        return FailoverReason.AUTH.value
    if status == 404 or "notfound" in name:
        return FailoverReason.NOT_FOUND.value
    if status == 402 or any(k in msg for k in _QUOTA_MARKERS):
        return FailoverReason.QUOTA.value
    if status == 429 or "ratelimit" in name or any(
        k in msg for k in ("429", "rate limit", "rate_limit", "too many requests")
    ):
        return FailoverReason.RATE_LIMIT.value
    if any(k in msg for k in ("401", "403", "unauthorized", "invalid api key", "authentication", "permission")):
        return FailoverReason.AUTH.value
    if any(k in msg for k in ("413", "context_length", "context window", "maximum context", "too many tokens")):
        return FailoverReason.CONTEXT_OVERFLOW.value
    if any(k in msg for k in ("empty response", "empty_response")):
        return FailoverReason.EMPTY_RESPONSE.value
    if (
        (status is not None and status >= 500)
        or any(
            k in name
            for k in (
                "timeout",
                "connection",
                "apiconnection",
                "serviceunavailable",
                "overloaded",
                "internalserver",
                "badgateway",
                "chunkedencodingerror",
                "remoteprotocolerror",
                "incompleteread",
                "streamerrored",
                "streamclosed",
            )
        )
        or any(
            k in msg
            for k in (
                "timeout",
                "timed out",
                "502",
                "503",
                "504",
                "500",
                "connection",
                "temporarily",
                "overloaded",
                "stream disconnected",
                "chunk decode",
            )
        )
    ):
        return FailoverReason.TRANSIENT.value
    if "quota" in msg:
        return FailoverReason.RATE_LIMIT.value
    return FailoverReason.FATAL.value


@dataclass
class _KeyState:
    key: str
    cooldown_until: float = 0.0
    failures: int = 0


class CredentialPool:
    """Priority-ordered multi-key credential pool with cooldown failover (hermes-agent)."""

    def __init__(self, keys: Sequence[str], *, clock: Callable[[], float] = time.monotonic) -> None:
        cleaned = [k for k in keys if k]
        if not cleaned:
            raise ValueError("CredentialPool requires at least one non-empty credential.")
        self._keys = [_KeyState(key=k) for k in cleaned]
        self._clock = clock

    def __len__(self) -> int:
        return len(self._keys)

    def acquire(self) -> str:
        """Return the highest-priority credential not currently in cooldown."""
        now = self._clock()
        for state in self._keys:
            if state.cooldown_until <= now:
                return state.key
        # All in cooldown: pick the one recovering soonest
        soonest = min(self._keys, key=lambda s: s.cooldown_until)
        return soonest.key

    def mark_failed(self, key: str, *, cooldown_s: float = 30.0) -> None:
        now = self._clock()
        for state in self._keys:
            if state.key == key:
                state.failures += 1
                state.cooldown_until = now + max(0.0, cooldown_s)
                break

    def mark_healthy(self, key: str) -> None:
        for state in self._keys:
            if state.key == key:
                state.failures = 0
                state.cooldown_until = 0.0
                break


def retry_stream_zero_event_safe(
    stream_factory: Callable[[], Iterator[Any]],
    *,
    max_attempts: int = 3,
    sleep_fn: Callable[[float], None] = lambda _s: None,
) -> Iterator[Any]:
    """Retry a streaming LLM call ONLY if zero events have been emitted yet (ag2 pattern)."""
    for attempt in range(1, max(1, max_attempts) + 1):
        emitted_any = False
        try:
            for event in stream_factory():
                emitted_any = True
                yield event
            if not emitted_any and attempt < max_attempts:
                sleep_fn(0.25 * attempt)
                continue
            return
        except Exception as exc:
            reason = classify_error(exc)
            retryable = reason in (FailoverReason.TRANSIENT.value, FailoverReason.RATE_LIMIT.value)
            if emitted_any or not retryable or attempt >= max_attempts:
                raise
            sleep_fn(0.25 * (2 ** (attempt - 1)))


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def repair_json_string(raw: str) -> str:
    """Repair common LLM JSON defects (fences, comments, single quotes, Python literals, truncation)."""
    if not raw:
        return "{}"
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    if not text.startswith(("{", "[")) and "{" in text:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            text = match.group(0).strip()
    # Strip single-line // comments outside URLs
    text = re.sub(r"(?<!:)//.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\bTrue\b", "true", text)
    text = re.sub(r"\bFalse\b", "false", text)
    text = re.sub(r"\bNone\b", "null", text)
    if "'" in text and '"' not in text:
        text = text.replace("'", '"')
    else:
        text = re.sub(r"(?<=[{,\s])'([A-Za-z0-9_$\-\.]+)'\s*:", r'"\1":', text)
        text = re.sub(r":\s*'([^']*)'(?=[,\s}\]])", r': "\1"', text)
    text = _TRAILING_COMMA_RE.sub(r"\1", text)
    open_curly, close_curly = text.count("{"), text.count("}")
    if open_curly > close_curly:
        text += "}" * (open_curly - close_curly)
    open_sq, close_sq = text.count("["), text.count("]")
    if open_sq > close_sq:
        text += "]" * (open_sq - close_sq)
    return text


def _parse_loose_mapping(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if not isinstance(raw, str):
        raise ValueError(f"Cannot repair non-mapping arguments of type {type(raw).__name__}")
    text = raw.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    for candidate in (text, _TRAILING_COMMA_RE.sub(r"\1", text), repair_json_string(text)):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    # Python literal fallback (single quotes, True/False/None)
    try:
        lit = ast.literal_eval(text)
        if isinstance(lit, dict):
            return lit
    except Exception:
        pass
    raise ValueError(f"Unable to parse malformed tool arguments: {text[:120]!r}")


def _coerce_value(val: Any, prop_schema: Mapping[str, Any], depth: int = 0) -> Any:
    if depth > 4:
        return val
    expected = prop_schema.get("type")
    if expected == "integer" and isinstance(val, str):
        try:
            return int(val.strip())
        except ValueError:
            return val
    if expected == "number" and isinstance(val, str):
        try:
            return float(val.strip())
        except ValueError:
            return val
    if expected == "boolean" and isinstance(val, str):
        low = val.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
    if expected == "array" and isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            return [val]
    if expected == "object" and isinstance(val, str):
        try:
            return _parse_loose_mapping(val)
        except ValueError:
            return val
    return val


def repair_arguments(tool_name: str, raw_args: Any, schema: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Deterministically repair malformed JSON/fences/literals and coerce types to schema."""
    args = _parse_loose_mapping(raw_args)
    props = (schema or {}).get("properties")
    if isinstance(props, Mapping):
        for key, prop_schema in props.items():
            if key in args and isinstance(prop_schema, Mapping):
                args[key] = _coerce_value(args[key], prop_schema)
    return args


class ReliabilityEngine:
    """Composite ReliabilityPort implementation combining repair, classification, and loop detection."""

    def __init__(self, *, repeat_threshold: int = 3, tool_aliases: Mapping[str, str] | None = None) -> None:
        self._repeat_threshold = max(2, int(repeat_threshold))
        self._tool_aliases = {k.lower(): v for k, v in (tool_aliases or {}).items()}

    @property
    def name(self) -> str:
        return "jaeger_reliability"

    def resolve_tool_alias(self, name: str) -> str:
        return self._tool_aliases.get(name.strip().lower(), name)

    def classify_error(self, error: Exception) -> str:
        return classify_error(error)

    def repair_arguments(self, tool_name: str, raw_args: Any, schema: Mapping[str, Any]) -> Mapping[str, Any]:
        return repair_arguments(tool_name, raw_args, schema)

    def check_loop(self, history: Sequence[Mapping[str, Any]]) -> bool:
        """Detect identical consecutive tool-call loops or ABAB oscillation."""
        if len(history) < self._repeat_threshold:
            return False
        sigs = [
            f"{h.get('tool')}:{json.dumps(h.get('arguments', {}), sort_keys=True, default=str)}"
            for h in history
        ]
        # Identical consecutive tail
        tail = sigs[-self._repeat_threshold :]
        if len(set(tail)) == 1:
            return True
        # ABAB oscillation (4+ entries alternating 2 calls)
        if len(sigs) >= 4 and sigs[-4] == sigs[-2] and sigs[-3] == sigs[-1] and sigs[-1] != sigs[-2]:
            return True
        return False
