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
        from jaeger_ai.core import context as _tcommon
        from jaeger_ai.core.memory import memory as _memmod
        _memmod.bind(layout)
        _tcommon._layout = layout
    except Exception:  # noqa: BLE001 — binding is best-effort for the probe
        pass


def _update_check() -> Any:
    """Informational Check: installed version vs the latest GitHub tag.
    Best-effort — an unreachable network degrades to 'couldn't check', and an
    available update is reported ``ok`` (newer-available is not 'unhealthy')."""
    import jaeger_ai

    from jaeger_ai.core import version_check
    from jaeger_ai.core.runtime.preflight import Check

    current = jaeger_ai.__version__
    latest = version_check.latest_version()
    if latest is None:
        detail = f"v{current} installed — couldn't reach GitHub to check"
    elif version_check.is_newer(latest, current):
        detail = f"v{current} installed — {latest} available · run `jaeger update`"
    else:
        detail = f"v{current} — up to date"
    return Check(name="version", category="update", ok=True, detail=detail)


def _probe_fda() -> bool | None:
    """True/False if we can determine Full Disk Access for this process, None
    if undeterminable. Probes a TCC-gated path (`TCC.db`) — readable only with
    FDA granted."""
    from pathlib import Path
    probe = Path.home() / "Library/Application Support/com.apple.TCC/TCC.db"
    try:
        with open(probe, "rb"):
            return True
    except PermissionError:
        return False
    except OSError:
        return None


def _fda_check() -> Any | None:
    """macOS only: does this process have Full Disk Access? Informational —
    FDA matters only for protected folders (Desktop / Documents / Downloads /
    external drives), so it's never a hard failure. Returns None off macOS."""
    import sys
    if sys.platform != "darwin":
        return None
    from jaeger_ai.core.runtime.preflight import Check
    granted = _probe_fda()
    if granted is False:
        detail = ("not granted — needed only for protected folders "
                  "(Desktop/Documents/Downloads/external drives). Grant in "
                  "System Settings → Privacy & Security → Full Disk Access.")
    elif granted is True:
        detail = "granted"
    else:
        detail = "could not determine"
    return Check(name="full_disk_access", category="system", ok=True, detail=detail)


class _DoctorRegistrationSentinel:
    """Stand-in passed to the skill loader so ``jaeger doctor`` can trigger
    a real discovery+registration pass and read back WHICH skills were
    skipped and why — the loader's ``_ToolCapturingAgent`` only needs
    ``tool_plain``/``tool`` to be callable; this is the same shape as
    ``main._RegistrationSentinel``, duplicated here to avoid doctor.py
    importing the CLI entry module."""

    def __getattr__(self, name: str) -> Any:  # noqa: D401
        return lambda *a, **k: None


def _skill_skip_checks(layout: Any) -> list[Any]:
    """0.9.3 Task 5 — one ``Check`` per skipped skill, category
    ``"skills"``, with an actionable ``fix``/``fix_cmd`` where the skip
    reason makes one derivable (pip install for an import error, a
    System Settings pane for a permission gap, ...). Skills skipped by
    deliberate config (``disabled by config``) or a forward-looking
    unimplemented manifest are left out — those aren't dependency
    problems, they're operator choices."""
    from jaeger_ai.core.runtime.preflight import Check
    from jaeger_ai.agent.skill_registry.skill_loader import (
        classify_skip, load_and_register, skip_fix_hint,
        _SKIP_CLASS_DISABLED, _SKIP_CLASS_UNSUPPORTED,
    )

    enabled_allowlist: list[str] | None = None
    try:
        from jaeger_ai.core.instance.schemas import Config, load_yaml
        cfg = load_yaml(layout.config_path, Config)
        enabled_allowlist = list(cfg.skills.enabled_base_skills) or None
    except Exception:  # noqa: BLE001 — no/partial config is fine, scan anyway
        pass

    try:
        report = load_and_register(
            _DoctorRegistrationSentinel(), layout,
            run_smoke_tests=True, enabled_allowlist=enabled_allowlist,
        )
    except Exception as exc:  # noqa: BLE001
        return [Check(name="skill_scan", category="skills", ok=False,
                       detail=f"couldn't scan skills: {type(exc).__name__}: {exc}")]

    checks: list[Any] = []
    for skill, reason in report.skipped:
        cls = classify_skip(reason)
        if cls in (_SKIP_CLASS_DISABLED, _SKIP_CLASS_UNSUPPORTED):
            continue
        fix, fix_cmd = skip_fix_hint(skill, reason, cls)
        headline = reason.splitlines()[0][:160] if reason else "skipped"
        checks.append(Check(
            name=f"skill:{skill.name}", category="skills", ok=False,
            detail=f"[{cls}] {headline}",
            fix=fix, fix_cmd=fix_cmd,
        ))
    return checks


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
    from jaeger_ai.core.runtime.preflight import (
        Check,
        check_environment,
        check_instance,
    )

    if layout is not None:
        _bind(layout)
        checks: list[Any] = check_instance(layout)
    else:
        checks = check_environment()

    # 0.9.3 Task 5 — skipped-skill visibility: one Check per skill the
    # loader couldn't register, with a class tag + actionable fix where
    # derivable. Instance-only (needs a layout to discover instance
    # skills against); best-effort, never blocks the rest of the report.
    if layout is not None:
        try:
            checks.extend(_skill_skip_checks(layout))
        except Exception as exc:  # noqa: BLE001
            checks.append(Check(
                name="skill_scan", category="skills", ok=False,
                detail=f"skill skip scan error: {type(exc).__name__}: {exc}",
            ))

    # Runtime substrate probe — folded in as ``runtime``-category Checks
    # so the renderer shows them in their own section. A probe failure is
    # surfaced, never allowed to crash the doctor.
    try:
        from jaeger_ai.core.diagnostics.probe import run_health_checks
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

    # macOS Full Disk Access readout (local, cheap) — guidance only.
    try:
        fda = _fda_check()
        if fda is not None:
            checks.append(fda)
    except Exception:  # noqa: BLE001 — diagnostics never crash the doctor
        pass
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
