"""The single doctor — one engine behind both surfaces.

JROS used to have two diagnostics paths that drifted: ``jaeger --doctor``
(pre-boot dependency + config checks, :mod:`jaeger_os.core.runtime.preflight`)
and ``jaeger health`` / ``system_health`` (the runtime substrate probe,
:mod:`jaeger_os.core.diagnostics.probe`). They checked different things,
so "the doctor is green" and "the agent actually works" could disagree.

:func:`run_doctor` runs BOTH — deps/config + runtime substrate (+ optional
deep agent-loop) — and returns a flat ``list[Check]`` so the existing
``preflight.format_report`` renderer shows the probe as its own
``runtime`` section. Exactly two callers:

  * user-facing   — ``jaeger doctor`` (the CLI)
  * agent-facing  — the ``self_check`` tool

Nothing else should reimplement health checks.
"""

from __future__ import annotations

from typing import Any


def _bind(layout: Any) -> None:
    """Bind memory + the tool sandbox to the instance so the runtime
    probe can read its paths. Idempotent — harmless when the agent has
    already bound (it just re-points at the same layout)."""
    try:
        from jaeger_os.agent.tools import _common as _tcommon
        from jaeger_os.core.memory import memory as _memmod
        _memmod.bind(layout)
        _tcommon._layout = layout
    except Exception:  # noqa: BLE001 — binding is best-effort for the probe
        pass


def _update_check() -> Any:
    """Informational Check: installed version vs the latest GitHub tag.
    Best-effort — an unreachable network degrades to 'couldn't check', and an
    available update is reported ``ok`` (newer-available is not 'unhealthy')."""
    import jaeger_os

    from jaeger_os.core import version_check
    from jaeger_os.core.runtime.preflight import Check

    current = jaeger_os.__version__
    latest = version_check.latest_version()
    if latest is None:
        detail = f"v{current} installed — couldn't reach GitHub to check"
    elif version_check.is_newer(latest, current):
        detail = f"v{current} installed — {latest} available · run `jaeger update`"
    else:
        detail = f"v{current} — up to date"
    return Check(name="version", category="update", ok=True, detail=detail)


def run_doctor(layout: Any = None, *, deep: bool = False,
               check_updates: bool = False) -> list[Any]:
    """Run the one doctor and return a flat ``list[Check]``.

    ``check_instance`` (environment deps + config + model.path + memory
    integrity) plus the runtime substrate probe (memory round-trip,
    tools, skills, drift parser). ``deep=True`` adds three live-agent
    turns. ``layout=None`` (no instance yet — a fresh ``pip install``)
    runs environment-only. ``check_updates=True`` (the CLI ``jaeger doctor``,
    not the agent's ``self_check``) appends a current-vs-latest readout.
    """
    from jaeger_os.core.runtime.preflight import (
        Check,
        check_environment,
        check_instance,
    )

    if layout is not None:
        _bind(layout)
        checks: list[Any] = check_instance(layout)
    else:
        checks = check_environment()

    # Runtime substrate probe — folded in as ``runtime``-category Checks
    # so the renderer shows them in their own section. A probe failure is
    # surfaced, never allowed to crash the doctor.
    try:
        from jaeger_os.core.diagnostics.probe import run_health_checks
        probe = run_health_checks(deep=deep)
        for c in probe.get("checks", []):
            checks.append(Check(
                name=str(c.get("name", "?")), category="runtime",
                ok=bool(c.get("ok")), detail=str(c.get("detail", "")),
            ))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check(
            name="runtime_probe", category="runtime", ok=False,
            detail=f"probe error: {type(exc).__name__}: {exc}",
        ))

    # Current-vs-latest readout — CLI doctor only (never the agent's
    # self_check; it shouldn't hit GitHub on every call). Best-effort.
    if check_updates:
        try:
            checks.append(_update_check())
        except Exception as exc:  # noqa: BLE001
            checks.append(Check(
                name="version", category="update", ok=True,
                detail=f"update check error: {type(exc).__name__}"))
    return checks


def doctor_summary(layout: Any = None, *, deep: bool = False) -> dict[str, Any]:
    """The agent-facing shape: run the doctor, roll up to a dict the
    ``self_check`` tool returns to the model."""
    checks = run_doctor(layout, deep=deep)
    passed = sum(1 for c in checks if c.ok)
    total = len(checks)
    return {
        "ok": passed == total,
        "passed": passed,
        "total": total,
        "deep": bool(deep),
        "checks": [
            {"name": c.name, "category": c.category, "ok": c.ok,
             "detail": c.detail}
            for c in checks
        ],
        "failures": [
            {"name": c.name, "category": c.category, "detail": c.detail}
            for c in checks if not c.ok
        ],
    }
