"""6-tier permission system + decorator + confirmation flow + safe modes.

The point of this module is to build the permission *muscle and
infrastructure* now, while Lilith runs on a laptop and the stakes are
low. When she eventually moves into a robot body, the same decorator
and the same policy machinery already have the seat-belt in.

Six tiers:

    0  READ_ONLY        Default-allowed reads (list files, search, read calendar)
    1  WRITE_LOCAL      Writes that need confirmation (edit a file, send a draft)
    2  EXTERNAL_EFFECT  API calls with side effects (post content, financial moves)
    3  HARDWARE         Hardware/safety-critical (motor control, e-stop)
                        Routes through confirmation like 1/2/4 — JROS is the
                        robot OS, so this tier is live here. The fail-safe
                        default (DenyAllProvider) still refuses it when no
                        real provider is wired. Until 0.5.0 it was
                        hard-denied ("reserved for JROS"), a leftover from
                        this layer's Lilith-on-a-laptop origin.
    4  PRIVILEGED       Privileged system ops (modify Lilith's config, install skills)
    5  DEV_BYPASS       Full bypass; explicit human override only

Policy modes (one-way door):

    NORMAL      Tier 0 auto-allows; tier 1/2/3/4 route through confirmation;
                tier 5 requires human override.
    READ_ONLY   Only tier 0 is allowed. Anything else denies.
    PAUSED      Nothing is allowed. Even reads are blocked.

Entering a safer mode is always allowed. *Exiting* a safer mode requires
``human_override=True`` — a tool call or a subagent cannot, on its own,
escape the safety mode it was placed in.

Policy lookup uses a ``contextvars`` variable, so subagents inherit the
parent's policy by default and tests can install their own policy in a
``with use_policy(...)`` block without leaking state.

# PORTABILITY: this module is Layer 1. It does not assume any
# particular UI for the confirmation flow — the launcher injects a
# concrete ``ConfirmationProvider`` at startup. The default provider
# (``DenyAllProvider``) is fail-safe.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import inspect
import json
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Protocol, TypeVar, cast, runtime_checkable


# --- Tier and mode enums ------------------------------------------------------


class PermissionTier(IntEnum):
    """The six tiers (lowest to highest impact). See module docstring."""

    READ_ONLY = 0
    WRITE_LOCAL = 1
    EXTERNAL_EFFECT = 2
    HARDWARE = 3
    PRIVILEGED = 4
    DEV_BYPASS = 5

    @property
    def description(self) -> str:
        """Human-readable description of the tier's intent."""
        return {
            PermissionTier.READ_ONLY: "default-allowed read",
            PermissionTier.WRITE_LOCAL: "local write requiring confirmation",
            PermissionTier.EXTERNAL_EFFECT: "operation with external side effects",
            PermissionTier.HARDWARE: "hardware / safety-critical (JROS only)",
            PermissionTier.PRIVILEGED: "privileged system operation",
            PermissionTier.DEV_BYPASS: "full bypass, human override only",
        }[self]


class PolicyMode(IntEnum):
    """How permissive the live policy is. ``NORMAL`` is the operating default."""

    NORMAL = 0
    READ_ONLY = 1
    PAUSED = 2


# --- Exceptions ---------------------------------------------------------------


class PermissionError(Exception):
    """Base class for permission failures.

    Named ``PermissionError`` shadows the builtin intentionally inside
    this module's public surface; consumers should import it as
    ``from jaeger_os.core.safety.permissions import PermissionError as ...`` if
    the name collision matters in their context.
    """


class PermissionDenied(PermissionError):
    """The current policy denies this request."""


class ConfirmationRequired(PermissionError):
    """The request needs confirmation but no provider was wired in.

    Raised when no ``ConfirmationProvider`` is configured at all
    (programming error). ``DenyAllProvider`` returning ``False`` raises
    :class:`PermissionDenied` instead — that is the safe default at
    runtime.
    """


class HumanOverrideRequired(PermissionError):
    """Only a human can authorize this — not a tool, subagent, or LLM."""


# --- Request / provider -------------------------------------------------------


@dataclass(frozen=True)
class PermissionRequest:
    """A request to perform a tier-tagged operation.

    Attributes:
        tier: The tier the operation is registered at.
        skill: The MCP server / skill the operation belongs to.
        operation: A short identifier for the specific tool call
            (``create_text_file``, ``send_email``, ...).
        summary: Optional one-line description shown to a human in the
            confirmation UI.
    """

    tier: PermissionTier
    skill: str
    operation: str
    summary: str = ""


@runtime_checkable
class ConfirmationProvider(Protocol):
    """Asks a human to approve a permission request.

    Implementations may be synchronous (CLI prompt, GUI dialog) or, in
    headless tests, just a stub. The launcher injects whichever surface
    is appropriate for the active embodiment.
    """

    def confirm(self, request: PermissionRequest) -> bool:
        """Return True iff the human approved the request."""
        ...


class DenyAllProvider:
    """Default — denies any request that requires confirmation.

    Fail-safe default. The launcher replaces this with a real CLI /
    GUI provider once UIs are wired up.
    """

    def confirm(self, request: PermissionRequest) -> bool:  # noqa: ARG002
        return False


class AllowAllProvider:
    """Test-only provider that approves every request.

    Lives here (not in tests/) because it is also the right thing to use
    in a strict ``--yes`` automation mode where the user has accepted
    that they will not be prompted. Document its use in any operator
    runbook that turns it on.
    """

    def confirm(self, request: PermissionRequest) -> bool:  # noqa: ARG002
        return True


@dataclass
class PermissionGrants:
    """Per-skill permission grants — so a 'yes' actually sticks.

    Confirmation is **per skill, not per call**. Once the user approves a
    skill, that skill stops asking:

    • plain *yes* → granted for the rest of this session (in memory).
    • *always*    → granted permanently — written to
      ``<instance>/permissions.json`` and reloaded on every boot.

    A skill the user never approved still prompts. The two zones keep a
    multi-step task (one ``computer_use`` job is dozens of clicks) from
    becoming a wall of identical prompts.
    """

    path: Path | None = None
    persistent: set[str] = field(default_factory=set)
    session: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, instance_dir: Any = None) -> "PermissionGrants":
        """Load the persisted grants for an instance. Missing / unreadable
        file ⇒ empty grants (every skill prompts)."""
        if not instance_dir:
            return cls()
        path = Path(instance_dir) / "permissions.json"
        persistent: set[str] = set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            persistent = {str(s) for s in data.get("granted_skills", [])}
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            pass
        return cls(path=path, persistent=persistent)

    def is_granted(self, skill: str) -> bool:
        return bool(skill) and (skill in self.persistent or skill in self.session)

    def grant_session(self, skill: str) -> None:
        """Approve ``skill`` for the rest of this session."""
        if skill:
            self.session.add(skill)

    def grant_persistent(self, skill: str) -> None:
        """Approve ``skill`` permanently — persisted across restarts."""
        if not skill:
            return
        self.session.add(skill)
        if skill not in self.persistent:
            self.persistent.add(skill)
            self._save()

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"granted_skills": sorted(self.persistent)}, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass


class ConsoleConfirmationProvider:
    """Asks the human to approve a tier-gated operation at the console.

    The interactive provider for the CLI / TUI. The launcher installs it
    at boot so a tier-1/2/4 tool (run code in the venv, install a
    package, …) prompts the user instead of being silently denied by
    :class:`DenyAllProvider`.

    Fail-safe: on a non-interactive stdin (benchmarks, the daemon, piped
    input) ``confirm`` denies without blocking — identical to
    ``DenyAllProvider``, so unattended runs never hang on ``input()``.

    Grants are **per skill** (see :class:`PermissionGrants`): *yes* holds
    for the session, *always* persists across restarts. An already-granted
    skill never prompts again.
    """

    def __init__(self, instance_dir: Any = None) -> None:
        self._grants = PermissionGrants.load(instance_dir)

    def confirm(self, request: "PermissionRequest") -> bool:
        skill = getattr(request, "skill", "") or ""
        if self._grants.is_granted(skill):
            return True
        if not sys.stdin.isatty():
            return False  # unattended — fail safe, never block
        tier = getattr(request.tier, "name", str(request.tier))
        op = f"{request.skill}.{request.operation}"
        print()
        print(f"  ⚠  permission needed — {op}  [{tier}]")
        if request.summary:
            print(f"     {request.summary}")
        try:
            ans = input(
                f"     allow?  [y]es (rest of session) / [N]o / "
                f"[a]lways (remember {skill or 'this'}) : "
            )
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        ans = ans.strip().lower()
        # First-letter match: "always" / "allow" / "a" all persist;
        # "yes" / "y" grant for the session.
        if ans.startswith("a"):
            self._grants.grant_persistent(skill)
            print(f"     ✓ remembered — {skill or 'this'} won't ask again")
            return True
        if ans.startswith("y"):
            self._grants.grant_session(skill)
            return True
        return False


# --- Policy -------------------------------------------------------------------


@dataclass
class PermissionPolicy:
    """Lilith's live permission policy.

    The policy decides whether a tier is allowed in the current mode,
    routes confirmation to the configured provider when needed, and
    enforces the one-way-door rule for safe modes.

    Attributes:
        mode: NORMAL / READ_ONLY / PAUSED. Mutable but transitions are
            gated by ``enter_safe_mode`` and ``request_normal_mode``.
        confirmation: Provider that asks a human for approval. Defaults
            to :class:`DenyAllProvider` (fail-safe).
    """

    mode: PolicyMode = PolicyMode.NORMAL
    confirmation: ConfirmationProvider = field(default_factory=DenyAllProvider)

    # ----- Tier check --------------------------------------------------------

    def check(self, request: PermissionRequest) -> None:
        """Raise if the request is denied; return ``None`` if allowed.

        The decision tree:

            mode == PAUSED       → always raise PermissionDenied
            mode == READ_ONLY    → only tier 0 allowed
            mode == NORMAL:
                tier 0           → allow
                tier 5 (DEV_BYPASS)→ HumanOverrideRequired
                tier 1, 2, 3, 4  → confirmation provider decides
                                   (tier 3 HARDWARE additionally fails
                                   closed at the capability layer while
                                   the system e-stop is latched — see
                                   jaeger_os.hardware.safety)

        Raises:
            PermissionDenied
            HumanOverrideRequired
        """
        if self.mode == PolicyMode.PAUSED:
            raise PermissionDenied(
                f"policy is PAUSED; refusing {request.skill}.{request.operation}"
            )
        if (
            self.mode == PolicyMode.READ_ONLY
            and request.tier != PermissionTier.READ_ONLY
        ):
            raise PermissionDenied(
                f"policy is READ_ONLY; tier {request.tier.name} blocked for "
                f"{request.skill}.{request.operation}"
            )

        # NORMAL mode below.
        if request.tier == PermissionTier.READ_ONLY:
            return

        if request.tier == PermissionTier.DEV_BYPASS:
            raise HumanOverrideRequired(
                f"tier 5 (DEV_BYPASS) requires explicit human override; "
                f"a tool or subagent cannot grant it. "
                f"({request.skill}.{request.operation})"
            )

        # Tiers 1, 2, 3, 4 — confirmation provider decides. HARDWARE
        # (3) rides the same flow: with no real provider wired the
        # DenyAllProvider default refuses it, and the capability layer
        # independently fails closed while the e-stop latch is engaged.
        approved = self.confirmation.confirm(request)
        if not approved:
            raise PermissionDenied(
                f"confirmation refused for {request.skill}.{request.operation} "
                f"(tier {request.tier.name})"
            )

    # ----- One-way door ------------------------------------------------------

    def enter_safe_mode(self, mode: PolicyMode) -> None:
        """Tighten the policy. Always permitted.

        ``mode`` must be a strictly *safer* level than the current one
        (READ_ONLY tighter than NORMAL; PAUSED tighter than READ_ONLY).
        Re-entering the same mode is a no-op.

        Raises:
            ValueError: when called with NORMAL (use
                :meth:`request_normal_mode` for that).
        """
        if mode == PolicyMode.NORMAL:
            raise ValueError(
                "enter_safe_mode does not loosen policy; "
                "use request_normal_mode(human_override=True)."
            )
        if mode.value < self.mode.value:
            raise ValueError(
                f"cannot move from {self.mode.name} to a less-safe mode "
                f"{mode.name} via enter_safe_mode"
            )
        self.mode = mode

    def request_normal_mode(self, *, human_override: bool = False) -> None:
        """Loosen the policy back to NORMAL.

        Only a human (or a hardware interlock) can take Lilith out of
        a safety mode. The ``human_override`` keyword is the explicit
        gate; tools / subagents calling this without it will hit
        :class:`HumanOverrideRequired`.

        Raises:
            HumanOverrideRequired: when ``human_override`` is False.
        """
        if not human_override:
            raise HumanOverrideRequired(
                "exiting a safe mode requires human_override=True; "
                "tools and subagents cannot self-exit."
            )
        self.mode = PolicyMode.NORMAL


# --- Live policy: contextvar overlay + process-wide install -------------------

# The fail-safe default. Also the sentinel current_policy() uses to tell
# "this context never had a policy set" apart from "a policy is active".
_DEFAULT_POLICY = PermissionPolicy()

_current_policy: contextvars.ContextVar[PermissionPolicy] = contextvars.ContextVar(
    "lilith_permission_policy",
    default=_DEFAULT_POLICY,
)

# Process-wide installed policy. A contextvar does NOT propagate into a
# thread started with threading.Thread — a fresh thread gets an empty
# context. The TUI runs every turn on a background worker thread, and
# pydantic-ai dispatches sync tools onto anyio worker threads; none of
# them inherit a policy install_policy() set on the main thread. Without
# this backstop current_policy() on the worker falls back to the
# DenyAllProvider default and silently refuses every tier-gated tool.
# install_policy() writes here so the policy resolves from any thread.
_installed_policy: PermissionPolicy | None = None


def current_policy() -> PermissionPolicy:
    """Return the policy active in the current context.

    Resolution order:
      1. an explicit :func:`use_policy` overlay set in this context;
      2. the process-wide policy from :func:`install_policy`;
      3. the fail-safe default (:class:`DenyAllProvider`).

    Step 2 is what lets a turn running on a worker thread — which never
    inherited the main thread's contextvars — still see the policy the
    launcher installed. Without it the worker resolves to the default and
    refuses every tier-1+ tool with "confirmation refused"."""
    pol = _current_policy.get()
    if pol is _DEFAULT_POLICY and _installed_policy is not None:
        return _installed_policy
    return pol


@contextlib.contextmanager
def use_policy(policy: PermissionPolicy) -> Iterator[PermissionPolicy]:
    """Install ``policy`` for the duration of the ``with`` block.

    Subagents inherit the current contextvar value; tests use this to
    pin a known policy without leaking state.
    """
    token = _current_policy.set(policy)
    try:
        yield policy
    finally:
        _current_policy.reset(token)


def install_policy(policy: PermissionPolicy) -> None:
    """Install ``policy`` as the process-wide active policy.

    Unlike :func:`use_policy`, this does not restore — it is the
    boot-time install for a long-running process (the launcher wires a
    real confirmation provider through here). It sets both the contextvar
    (so the installing context sees it directly) and a process-wide
    global, so a worker thread that never inherited the contextvar — the
    TUI runs turns on one — still resolves to it via :func:`current_policy`."""
    global _installed_policy
    _installed_policy = policy
    _current_policy.set(policy)


# --- requires_tier decorator --------------------------------------------------


F = TypeVar("F", bound=Callable[..., Any])


def requires_tier(
    tier: PermissionTier,
    *,
    skill: str,
    operation: str,
    summary: str = "",
) -> Callable[[F], F]:
    """Gate a callable on the live :class:`PermissionPolicy`.

    Usage::

        @requires_tier(
            PermissionTier.WRITE_LOCAL,
            skill="filesystem",
            operation="create_text_file",
            summary="write a file under ~/.lilith/workspace/",
        )
        def create_text_file(path: str, content: str) -> None:
            ...

    Works on both sync and async functions. The check happens before
    the wrapped function runs; if the policy raises, the wrapped
    function never executes.

    Parameters:
        tier: Which permission tier this operation belongs to.
        skill: The owning skill / MCP server name.
        operation: Short, stable identifier for this operation.
        summary: Optional one-line description shown in confirmation
            UIs.

    Returns:
        A decorator that preserves the wrapped function's signature.
    """

    request_template = PermissionRequest(
        tier=tier,
        skill=skill,
        operation=operation,
        summary=summary,
    )

    def decorate(fn: F) -> F:
        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrap(*args: Any, **kwargs: Any) -> Any:
                current_policy().check(request_template)
                return await fn(*args, **kwargs)

            # Tag the wrapper so introspection tools can recover the tier.
            async_wrap.__lilith_permission__ = request_template  # type: ignore[attr-defined]
            return cast(F, async_wrap)

        @functools.wraps(fn)
        def sync_wrap(*args: Any, **kwargs: Any) -> Any:
            current_policy().check(request_template)
            return fn(*args, **kwargs)

        sync_wrap.__lilith_permission__ = request_template  # type: ignore[attr-defined]
        return cast(F, sync_wrap)

    return decorate


def get_tier(fn: Callable[..., Any]) -> PermissionTier | None:
    """Recover the tier a callable was decorated with, if any.

    Returns ``None`` if ``fn`` is not a ``requires_tier``-wrapped
    callable. Used by the registry to validate that every tool a skill
    exposes carries an explicit tier.
    """
    request: PermissionRequest | None = getattr(fn, "__lilith_permission__", None)
    if request is None:
        return None
    return request.tier


def get_permission_request(fn: Callable[..., Any]) -> PermissionRequest | None:
    """Recover the full :class:`PermissionRequest` template attached to ``fn``.

    Mirrors :func:`get_tier` but returns the whole request — useful for
    surfaces that want to render the operation summary.
    """
    return getattr(fn, "__lilith_permission__", None)


# Alias used by tests and a future static AST scan that walks every
# function in lilith.skills.* and verifies it carries a tier.
def is_tier_decorated(fn: Callable[..., Any]) -> bool:
    """True iff ``fn`` was wrapped with :func:`requires_tier`."""
    return inspect.isfunction(fn) and hasattr(fn, "__lilith_permission__")


__all__ = [
    "AllowAllProvider",
    "ConfirmationProvider",
    "ConfirmationRequired",
    "ConsoleConfirmationProvider",
    "DenyAllProvider",
    "HumanOverrideRequired",
    "PermissionDenied",
    "PermissionError",
    "PermissionPolicy",
    "PermissionRequest",
    "PermissionTier",
    "PolicyMode",
    "current_policy",
    "get_permission_request",
    "get_tier",
    "install_policy",
    "is_tier_decorated",
    "requires_tier",
    "use_policy",
]
