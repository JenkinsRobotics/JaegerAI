"""The effect ledger — an authoritative action happens at most once.

Resumption creates a hazard that plain retries do not: the run comes
back and wants to re-do the step it was on. If that step sent the email,
charged the card, or filed the PR, "just run it again" is a bug with a
blast radius outside the process.

So authoritative side effects go through ``once``:

    result, executed = ledger.once("email:invoice-42", "send_email", send)

``once`` claims the key first, performs the effect, then records the
result. Three outcomes, and the third is the point of the module:

``done``
    The effect already ran. The stored result comes back, the callable
    is never invoked, ``executed`` is False.

``fresh``
    The key was unclaimed. The callable runs, the result is recorded.

``pending``
    A previous process claimed this key and never came back. It is
    genuinely unknown whether the effect landed — the crash may have
    happened before or after the email left. ``once`` raises
    ``EffectIndeterminate`` rather than choosing.

That refusal is the design. A model asked "did the email send?" will
answer, fluently, either way. The ledger will not: it escalates to
whoever can actually check, who then calls ``resolve`` (it happened,
here is the result) or ``abandon`` (it did not, the key is free again).
Silent re-execution and silent skipping are both worse than a stop.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

from jaeger_agent.cognition.lifecycle import now as _now


class EffectError(RuntimeError):
    """Bad ledger usage — unknown key, or resolving a settled effect."""


class EffectIndeterminate(EffectError):
    """A claim exists with no recorded outcome. A human or a checker
    decides; the runtime will not guess."""

    def __init__(self, key: str, claimed_at: str) -> None:
        super().__init__(
            f"effect {key!r} was claimed at {claimed_at} and never completed — "
            "verify externally, then resolve() or abandon() it"
        )
        self.key = key
        self.claimed_at = claimed_at


@dataclass(slots=True)
class Effect:
    key: str
    action: str
    status: str            # "pending" | "done"
    result: Any = None
    run_id: str | None = None
    claimed_at: str = ""
    completed_at: str | None = None


@runtime_checkable
class EffectLedger(Protocol):
    def once(self, key: str, action: str, fn: Callable[[], Any], *,
             run_id: str | None = None) -> tuple[Any, bool]: ...

    def get(self, key: str) -> Effect | None: ...

    def list(self, *, status: str | None = None) -> list[Effect]: ...

    def resolve(self, key: str, result: Any = None) -> Effect: ...

    def abandon(self, key: str) -> None: ...


def _settled(effect: Effect) -> None:
    if effect.status == "done":
        raise EffectError(f"effect {effect.key!r} is already done")


class InMemoryEffectLedger:
    def __init__(self) -> None:
        self._items: dict[str, Effect] = {}
        self._lock = threading.Lock()

    def once(self, key: str, action: str, fn: Callable[[], Any], *,
             run_id: str | None = None) -> tuple[Any, bool]:
        with self._lock:
            existing = self._items.get(key)
            if existing is not None:
                if existing.status == "done":
                    return existing.result, False
                raise EffectIndeterminate(key, existing.claimed_at)

            self._items[key] = Effect(
                key=key, action=action, status="pending",
                run_id=run_id, claimed_at=_now(),
            )
        # Anything raised here leaves the claim pending on purpose: the
        # effect may have partially landed, and that is exactly the case
        # a retry must not silently repeat. The lock is released so a
        # concurrent resolve/abandon can race the crash case, which is
        # the situation the ledger exists to make explicit.
        result = fn()
        return self.resolve(key, result).result, True

    def get(self, key: str) -> Effect | None:
        with self._lock:
            return self._items.get(key)

    def list(self, *, status: str | None = None) -> list[Effect]:
        with self._lock:
            items = list(self._items.values())
        if status is None:
            return items
        return [item for item in items if item.status == status]

    def resolve(self, key: str, result: Any = None) -> Effect:
        with self._lock:
            effect = self._items.get(key)
            if effect is None:
                raise EffectError(f"no effect {key!r}")
            _settled(effect)
            effect.status = "done"
            effect.result = result
            effect.completed_at = _now()
            return effect

    def abandon(self, key: str) -> None:
        with self._lock:
            effect = self._items.get(key)
            if effect is None:
                raise EffectError(f"no effect {key!r}")
            _settled(effect)
            del self._items[key]


__all__ = [
    "Effect",
    "EffectError",
    "EffectIndeterminate",
    "EffectLedger",
    "InMemoryEffectLedger",
]
