"""ModelRouter, StickyFallbackModel, and deterministic ReplayModel.

Harvested from:
- hermes-agent (`auxiliary_client.py`): routes side tasks (compression,
  classification, title gen) to fast/cheap/local auxiliary models.
- pydantic-ai (`model_fallback.py`) + agno (`fallback.py`): sticky failover
  across subsequent turns to preserve KV prompt-cache prefix hits, with
  failure-class chains (`rate_limit`, `context_overflow`, `error`).
- SWE-agent (`models.py`): deterministic `ReplayModel` for zero-API-cost tests.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from jaeger_contracts import ModelPort, ModelProfile

from .catalog import ModelCatalog


class ReplayModel:
    """Deterministic ModelPort test double replaying queued responses (SWE-agent)."""

    def __init__(
        self,
        responses: Sequence[Mapping[str, Any] | Exception],
        *,
        model_id: str = "local/mlx-qwen3-coder",
        catalog: ModelCatalog | None = None,
    ) -> None:
        self._model_id = model_id
        self._catalog = catalog or ModelCatalog()
        self._queue: deque[Mapping[str, Any] | Exception] = deque(responses)
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return f"replay:{self._model_id}"

    def profile(self, model_id: str | None = None) -> ModelProfile:
        return self._catalog.resolve(model_id or self._model_id)

    def complete(self, messages: Sequence[Mapping[str, Any]], **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append({"messages": list(messages), "kwargs": dict(kwargs)})
        if not self._queue:
            raise RuntimeError(f"ReplayModel({self._model_id}) exhausted response queue.")
        item = self._queue.popleft()
        if isinstance(item, Exception):
            raise item
        return dict(item)


class CallableModel:
    """Adapter wrapping any provider callable into a ModelPort."""

    def __init__(
        self,
        model_id: str,
        fn: Callable[[Sequence[Mapping[str, Any]], dict[str, Any]], Mapping[str, Any]],
        *,
        catalog: ModelCatalog | None = None,
    ) -> None:
        self._model_id = model_id
        self._fn = fn
        self._catalog = catalog or ModelCatalog()

    @property
    def name(self) -> str:
        return self._model_id

    def profile(self, model_id: str | None = None) -> ModelProfile:
        return self._catalog.resolve(model_id or self._model_id)

    def complete(self, messages: Sequence[Mapping[str, Any]], **kwargs: Any) -> Mapping[str, Any]:
        return self._fn(messages, kwargs)


@dataclass(frozen=True)
class ModelRequestAttempt:
    """Audit record for one model attempt (Pydantic-AI carry_attempts pattern)."""

    model_name: str
    ok: bool
    error_type: str = ""
    error: str = ""


@dataclass(frozen=True)
class ResponseFold:
    """Pure stream fold state (OpenCode llm.ts ResponseFold pattern)."""

    text: str = ""
    reasoning: str = ""
    tool_calls: tuple[dict[str, Any], ...] = ()
    finish_reason: str | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)

    def apply(self, event: Mapping[str, Any]) -> "ResponseFold":
        kind = str(event.get("type") or "")
        if kind == "text_delta":
            return ResponseFold(
                text=self.text + str(event.get("delta") or ""),
                reasoning=self.reasoning,
                tool_calls=self.tool_calls,
                finish_reason=self.finish_reason,
                usage=self.usage,
            )
        if kind == "reasoning_delta":
            return ResponseFold(
                text=self.text,
                reasoning=self.reasoning + str(event.get("delta") or ""),
                tool_calls=self.tool_calls,
                finish_reason=self.finish_reason,
                usage=self.usage,
            )
        if kind == "tool_call":
            tc = dict(event.get("tool_call") or {})
            return ResponseFold(
                text=self.text,
                reasoning=self.reasoning,
                tool_calls=(*self.tool_calls, tc),
                finish_reason=self.finish_reason,
                usage=self.usage,
            )
        if kind == "finish":
            merged_usage = {**dict(self.usage), **dict(event.get("usage") or {})}
            return ResponseFold(
                text=self.text,
                reasoning=self.reasoning,
                tool_calls=self.tool_calls,
                finish_reason=str(event.get("finish_reason") or "stop"),
                usage=merged_usage,
            )
        return self


@dataclass
class StickyFallbackModel:
    """Failover ModelPort that pins the healthy fallback to preserve prompt caches,
    re-prepares requests per candidate, and records every failed attempt."""

    primary: ModelPort
    fallbacks: tuple[ModelPort, ...] = ()
    overflow_fallbacks: tuple[ModelPort, ...] = ()
    sticky: bool = True
    prepare_request: Callable[[ModelPort, Sequence[Mapping[str, Any]], dict[str, Any]], tuple[Sequence[Mapping[str, Any]], dict[str, Any]]] | None = None
    _pinned: ModelPort | None = field(default=None, init=False, repr=False)
    last_attempts: list[ModelRequestAttempt] = field(default_factory=list, init=False, repr=False)

    @property
    def name(self) -> str:
        active = self._pinned or self.primary
        return f"sticky_fallback({active.name})"

    @property
    def active_model(self) -> ModelPort:
        return self._pinned or self.primary

    def reset_sticky(self) -> None:
        self._pinned = None

    def profile(self, model_id: str) -> ModelProfile:
        return self.active_model.profile(model_id)

    def _invoke(self, model: ModelPort, messages: Sequence[Mapping[str, Any]], kwargs: dict[str, Any]) -> Mapping[str, Any]:
        req_msgs, req_kw = (
            self.prepare_request(model, messages, dict(kwargs))
            if self.prepare_request is not None
            else (messages, dict(kwargs))
        )
        return model.complete(req_msgs, **req_kw)

    def complete(self, messages: Sequence[Mapping[str, Any]], **kwargs: Any) -> Mapping[str, Any]:
        self.last_attempts = []
        first = self._pinned or self.primary
        candidates: list[ModelPort] = [first]
        for m in (self.primary, *self.fallbacks):
            if m not in candidates:
                candidates.append(m)

        last_exc: Exception | None = None
        for idx, model in enumerate(candidates):
            try:
                res = self._invoke(model, messages, kwargs)
                self.last_attempts.append(ModelRequestAttempt(model_name=model.name, ok=True))
                if self.sticky and model is not self.primary:
                    self._pinned = model
                return res
            except Exception as exc:
                last_exc = exc
                self.last_attempts.append(
                    ModelRequestAttempt(model_name=model.name, ok=False, error_type=type(exc).__name__, error=str(exc)[:240])
                )
                msg = str(exc).lower()
                if idx == 0 and self.overflow_fallbacks and any(
                    tok in msg for tok in ("context_length", "context window", "too many tokens", "413")
                ):
                    for ov in self.overflow_fallbacks:
                        try:
                            res = self._invoke(ov, messages, kwargs)
                            self.last_attempts.append(ModelRequestAttempt(model_name=ov.name, ok=True))
                            if self.sticky:
                                self._pinned = ov
                            return res
                        except Exception as ov_exc:
                            last_exc = ov_exc
                            self.last_attempts.append(
                                ModelRequestAttempt(model_name=ov.name, ok=False, error_type=type(ov_exc).__name__, error=str(ov_exc)[:240])
                            )
        assert last_exc is not None
        raise last_exc


class ModelRouter:
    """Routes primary, auxiliary (compression/classify), and privacy-gated turns."""

    def __init__(
        self,
        *,
        primary: ModelPort,
        auxiliary: ModelPort | None = None,
        local_only_model: ModelPort | None = None,
        catalog: ModelCatalog | None = None,
    ) -> None:
        self._primary = primary
        self._auxiliary = auxiliary or primary
        self._local = local_only_model
        self._catalog = catalog or ModelCatalog()

    @property
    def name(self) -> str:
        return f"router({self._primary.name})"

    def select(self, *, task_kind: str = "primary", sensitive: bool = False) -> ModelPort:
        if sensitive:
            if self._local is not None:
                return self._local
            # Fail closed on sensitive egress if primary is cloud-only
            if not self._primary.profile(self._primary.name).local_only:
                raise PermissionError("Sensitive turn blocked: no local-only model configured.")
            return self._primary
        if task_kind in ("compact", "classify", "title", "auxiliary"):
            return self._auxiliary
        return self._primary

    def profile(self, model_id: str) -> ModelProfile:
        return self._catalog.resolve(model_id)

    def complete(self, messages: Sequence[Mapping[str, Any]], **kwargs: Any) -> Mapping[str, Any]:
        task_kind = str(kwargs.pop("task_kind", "primary"))
        sensitive = bool(kwargs.pop("sensitive", False))
        target = self.select(task_kind=task_kind, sensitive=sensitive)
        return target.complete(messages, **kwargs)
