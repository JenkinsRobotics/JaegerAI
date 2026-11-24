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


@dataclass
class StickyFallbackModel:
    """Failover ModelPort that pins the healthy fallback to preserve prompt caches."""

    primary: ModelPort
    fallbacks: tuple[ModelPort, ...] = ()
    overflow_fallbacks: tuple[ModelPort, ...] = ()
    sticky: bool = True
    _pinned: ModelPort | None = field(default=None, init=False, repr=False)

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

    def complete(self, messages: Sequence[Mapping[str, Any]], **kwargs: Any) -> Mapping[str, Any]:
        first = self._pinned or self.primary
        candidates: list[ModelPort] = [first]
        for m in (self.primary, *self.fallbacks):
            if m not in candidates:
                candidates.append(m)

        last_exc: Exception | None = None
        for idx, model in enumerate(candidates):
            try:
                res = model.complete(messages, **kwargs)
                if self.sticky and model is not self.primary:
                    self._pinned = model
                return res
            except Exception as exc:
                last_exc = exc
                msg = str(exc).lower()
                if idx == 0 and self.overflow_fallbacks and any(
                    tok in msg for tok in ("context_length", "context window", "too many tokens", "413")
                ):
                    for ov in self.overflow_fallbacks:
                        try:
                            res = ov.complete(messages, **kwargs)
                            if self.sticky:
                                self._pinned = ov
                            return res
                        except Exception as ov_exc:
                            last_exc = ov_exc
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
