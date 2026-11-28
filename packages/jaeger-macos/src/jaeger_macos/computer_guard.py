"""Fail-closed macOS Computer-Use safety guard & 4-stage audit record.

Adapted from Project AIRI's MIT-licensed ``computer-use-mcp`` safety model:
- Blocks desktop/UI automation against sensitive apps (credential managers,
  System Settings, Activity Monitor, and the host assistant itself).
- Keeps model decision, authorization decision, execution delivery, and
  business verification strictly separate so exit-code 0 or delivered input is
  never conflated with verified task completion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import time
from typing import Any, Iterable

DEFAULT_DENY_APPS: frozenset[str] = frozenset({
    "1password",
    "1password 7",
    "bitwarden",
    "keychain access",
    "passwords",
    "system settings",
    "system preferences",
    "activity monitor",
    "disk utility",
    "jaeger",
    "jaegerai",
})

DEFAULT_DENY_TITLE_TOKENS: frozenset[str] = frozenset({
    "keychain",
    "1password",
    "password manager",
    "private key",
    "recovery key",
    "seed phrase",
})


@dataclass(frozen=True)
class ComputerUseDecision:
    allowed: bool
    app_name: str
    window_title: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ComputerUseAuditRecord:
    """Four-stage execution record separating dispatch from verified completion."""

    action: str
    target_app: str
    model_decision: dict[str, Any]
    authorization: dict[str, Any]
    execution: dict[str, Any] = field(default_factory=lambda: {"status": "pending"})
    business_verification: dict[str, Any] = field(default_factory=lambda: {"status": "unverified"})
    timestamp: float = field(default_factory=time.time)

    def mark_delivered(self, *, details: str = "") -> None:
        """Record delivery without claiming business verification."""
        self.execution = {"status": "delivered", "details": details}

    def mark_verified(self, *, evidence: str) -> None:
        self.business_verification = {"status": "verified", "evidence": evidence}

    def mark_failed(self, *, error: str) -> None:
        self.execution = {"status": "failed", "error": error}
        self.business_verification = {"status": "failed", "evidence": error}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_app_automation_allowed(
    app_name: str,
    *,
    window_title: str = "",
    extra_deny_apps: Iterable[str] = (),
    extra_deny_titles: Iterable[str] = (),
) -> ComputerUseDecision:
    """Fail-closed check before focusing, clicking, typing, or scripting a GUI app."""
    app_clean = (app_name or "").strip()
    title_clean = (window_title or "").strip()
    if not app_clean:
        return ComputerUseDecision(
            allowed=False,
            app_name="",
            window_title=title_clean,
            reason="target app name is required (fail-closed)",
        )
    deny_apps = DEFAULT_DENY_APPS | {a.strip().lower() for a in extra_deny_apps if a and a.strip()}
    app_low = app_clean.lower()
    if app_low in deny_apps or any(app_low.startswith(d + " ") for d in deny_apps):
        return ComputerUseDecision(
            allowed=False,
            app_name=app_clean,
            window_title=title_clean,
            reason=f"blocked by sensitive-app deny list: {app_clean}",
        )
    deny_titles = DEFAULT_DENY_TITLE_TOKENS | {t.strip().lower() for t in extra_deny_titles if t and t.strip()}
    title_low = title_clean.lower()
    for token in deny_titles:
        if token and token in title_low:
            return ComputerUseDecision(
                allowed=False,
                app_name=app_clean,
                window_title=title_clean,
                reason=f"blocked by sensitive window title token: {token}",
            )
    return ComputerUseDecision(
        allowed=True,
        app_name=app_clean,
        window_title=title_clean,
        reason="allowed",
    )


__all__ = [
    "ComputerUseAuditRecord",
    "ComputerUseDecision",
    "DEFAULT_DENY_APPS",
    "DEFAULT_DENY_TITLE_TOKENS",
    "check_app_automation_allowed",
]
