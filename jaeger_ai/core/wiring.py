"""Loud-in-development guards for wiring that must not fail silently.

The tree is full of defensive fallbacks — ``if not d.exists(): return []``,
``except Exception: return {}`` — and individually every one is correct: a
corrupt file must not kill a boot, and a missing optional directory is not
an error. Collectively they produce one failure mode that has bitten this
codebase repeatedly:

    A disconnected component is indistinguishable from a
    connected one that had nothing to do.

``discover_migrations()`` returning ``[]`` read as "no migrations pending"
for as long as its directory was missing — from six call sites, including
boot, with no log line. The runner was not broken in a way anything could
see; it was quietly idle.

This module keeps the production behaviour (degrade, never crash) while
making the *development and test* signal loud, so a broken wire is caught
by the suite that runs on every change rather than by an operator months
later.

Use :func:`expect_path` for a directory or file whose absence means the
wiring is wrong rather than the feature being unused::

    if not expect_path(MIGRATIONS_DIR, "migration scripts directory"):
        return []

In production that logs a warning and returns ``False``. Under pytest, or
with ``JAEGER_STRICT_WIRING=1``, it raises :class:`WiringError`.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


class WiringError(RuntimeError):
    """A component's wiring target is missing. Raised only in strict mode."""


def strict_wiring() -> bool:
    """True when a missing wiring target should raise rather than warn.

    Strict under pytest (so the suite catches broken wiring) and whenever
    ``JAEGER_STRICT_WIRING`` is set, which lets an operator debug a quietly
    idle subsystem without editing code. Never strict in a normal run: a
    missing optional directory must not stop somebody's agent from booting.
    """
    raw = os.environ.get("JAEGER_STRICT_WIRING", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return "pytest" in sys.modules


def expect_path(path: Path | str, what: str, *, strict: bool | None = None) -> bool:
    """Assert a wiring target exists. ``True`` when present.

    Absent: logs a warning naming the path and what was expected, and
    returns ``False`` so the caller takes its existing degraded branch. In
    strict mode raises :class:`WiringError` instead — the message is the
    one a developer needs, not "returned empty".
    """
    target = Path(path)
    if target.exists():
        return True
    message = f"{what} not found at {target} — this component is wired to nothing"
    if strict if strict is not None else strict_wiring():
        raise WiringError(message)
    logger.warning("%s", message)
    return False


def report_degraded(
    what: str,
    exc: BaseException,
    *,
    logger_: logging.Logger | None = None,
    strict: bool | None = None,
) -> None:
    """Record that something failed and was degraded rather than fatal.

    The house rule for the ~548 defensive handlers in this tree. They are
    not a bug — "a corrupt file means no overrides, not a dead agent" is
    correct, and blanket-removing them would trade resilience for noise.
    The bug is that a swallowed failure and a genuine no-op look identical
    from outside, which is how a broken migration runner survived six call
    sites for a release.

    Policy, applied to critical paths first (discovery routines, bridge
    operations, plugin initialisation):

    1. **Keep the fallback.** Production still degrades instead of crashing.
    2. **Narrow the catch** where the failure modes are known —
       ``FileNotFoundError``, ``KeyError``, ``json.JSONDecodeError`` — and
       stay broad only where third-party code can raise anything.
    3. **Always log with ``exc_info=True``.** A message without a traceback
       tells you something failed and never where.
    4. **Be loud in dev/test.** Under pytest or ``JAEGER_STRICT_WIRING=1``
       this re-raises, so a suite catches what production tolerates.

    Use at a handler that would otherwise ``pass``::

        except (OSError, json.JSONDecodeError) as exc:
            report_degraded("reading the skill manifest", exc)
            return {}
    """
    log = logger_ or logger
    message = f"{what} failed; continuing in a degraded state"
    if strict if strict is not None else strict_wiring():
        raise WiringError(f"{message}: {exc}") from exc
    log.warning("%s: %s", message, exc, exc_info=True)


__all__ = ["WiringError", "expect_path", "report_degraded", "strict_wiring"]
