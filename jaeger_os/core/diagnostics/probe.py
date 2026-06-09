"""The lean-fast probe set.

Eight checks, each idempotent and individually under ~250 ms:

  1. layout          — required dirs writable
  2. file_sandbox    — write + read + delete a probe file under skills/
  3. memory          — remember + recall + forget round trip
  4. time            — get_time returns a timestamp
  5. calculate       — calculator answers 2+2 = 4
  6. tool_registry   — every CORE tool name resolves
  7. skills_loaded   — at least one skill discovered
  8. drift_parser    — parses a synthetic tool call

Why these eight: they cover the layers most likely to break silently
after a config or refactor change — instance binding, sandbox path
rules, memory store schema, tool registration, skill discovery, the
parser the model's text has to survive. None touches the LLM (that
would push wall time past 3s and break the "safe to run from cron"
property). A separate ``deep`` mode can add LLM checks later.

Each check is a ``HealthCheck`` callable returning ``HealthResult``.
The runner calls them in order and rolls up totals; failures don't
short-circuit the rest of the probe.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class HealthResult:
    """One probe's outcome."""
    name: str
    ok: bool
    detail: str = ""
    elapsed_ms: float = 0.0


@dataclass(frozen=True)
class HealthCheck:
    """A probe — name + the callable that runs it."""
    name: str
    fn: Callable[[], tuple[bool, str]]


# ── individual checks ───────────────────────────────────────────────


def _check_layout() -> tuple[bool, str]:
    """Are the per-instance directories present and writable? A
    read-only filesystem (USB drive, NixOS store accidentally
    selected as instance root) breaks every later check, so this
    runs first and gives a decisive failure when it bites."""
    from jaeger_os.agent.tools._common import _require_layout
    layout = _require_layout()
    for attr in ("logs_dir", "memory_dir", "skills_dir"):
        d = getattr(layout, attr, None)
        if d is None:
            return False, f"layout has no {attr!r}"
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            return False, f"{attr} not writable: {type(exc).__name__}: {exc}"
    return True, f"root={layout.root}"


def _check_file_sandbox() -> tuple[bool, str]:
    """Write + read + delete a probe file via the real sandbox path
    resolver. Catches a broken ``_resolve_under`` rule or a permission
    glitch on the skills/ directory."""
    from jaeger_os.agent.tools._common import _require_layout
    layout = _require_layout()
    probe = layout.skills_dir / f"_health_probe_{uuid.uuid4().hex[:8]}.txt"
    body = "ok"
    try:
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text(body, encoding="utf-8")
        read_back = probe.read_text(encoding="utf-8")
        if read_back != body:
            return False, "round-trip mismatch — sandbox returned stale content"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        try:
            probe.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass
    return True, "write+read+delete ok"


def _check_memory() -> tuple[bool, str]:
    """Memory remember/recall/forget round-trip. Catches schema drift
    on the SQLite ``facts`` table or a broken InstanceLayout binding
    (the memory store reads layout.memory_dir at every call).

    NB on the import shape: ``from jaeger_os.agent.tools import memory``
    resolves to the ``memory()`` umbrella *function* (re-exported from
    ``core.tools.__init__``) rather than the submodule of the same
    name — Python's name resolution picks the function attribute over
    the submodule because both live on the package. Importing the
    individual verbs explicitly avoids the shadowing.
    """
    from jaeger_os.agent.tools.memory import remember, recall, forget
    key = f"_health_probe_{uuid.uuid4().hex[:8]}"
    sentinel = "alive"
    try:
        remember(key=key, value=sentinel)
        out = recall(key=key)
        recalled = out.get("value") if isinstance(out, dict) else None
        if recalled != sentinel:
            return False, f"recall returned {recalled!r}, expected {sentinel!r}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        try:
            forget(key=key)
        except Exception:  # noqa: BLE001
            pass
    return True, "remember+recall+forget round trip ok"


def _check_time() -> tuple[bool, str]:
    """get_time returns a timestamp-ish string. Catches a broken
    ``time_and_math`` import or a recent rename."""
    from jaeger_os.agent.tools import get_time
    out = get_time()
    text = out if isinstance(out, str) else \
        (out.get("time") if isinstance(out, dict) else str(out))
    if not text or ":" not in text:
        return False, f"unexpected get_time output: {out!r}"
    return True, str(text)[:40]


def _check_calculate() -> tuple[bool, str]:
    """calculator answers 2+2 = 4. Round-trip through the same tool
    the agent uses, not a private eval."""
    from jaeger_os.agent.tools import calculate
    out = calculate(expression="2+2")
    body = str(out.get("result") if isinstance(out, dict) else out)
    if "4" not in body:
        return False, f"2+2 returned {body!r}"
    return True, f"2+2 = {body}"


def _check_tool_registry() -> tuple[bool, str]:
    """Every name in CORE resolves to a registered tool. Catches a
    rename that left the toolset config dangling against a tool that
    no longer exists (the lean-surface filter would silently hide it
    without this check).

    Source-of-truth precedence:
      1. **Phase-9 JaegerAgent** — ``agent._dispatch_by_name``
         (the live dispatch map; cached in ``_jaeger_agents_by_session``).
      2. **Legacy pydantic-ai agent** — ``agent._function_toolset.tools``
         (still in the codebase but no longer the active loop).
      3. **No agent booted** — return ok with a "not checked" message
         rather than scan ``dir(jaeger_os.agent.tools)``: the Python
         function names there don't match the agent-facing names
         CORE uses (e.g. ``read_file`` vs ``file_read``), so a naive
         scan would always false-negative.
    """
    from jaeger_os.agent.skill_registry.toolsets import CORE

    registered: set[str] = set()
    source = "none"

    # 1) Phase-9 JaegerAgent — pick any session (they share the
    # registered tool set; ``_dispatch_by_name`` is keyed on
    # ``ToolDef.name``, the agent-facing name).
    try:
        from jaeger_os.main import _jaeger_agents_by_session
        for jaeger_agent in _jaeger_agents_by_session.values():
            dispatch_map = getattr(jaeger_agent, "_dispatch_by_name", None)
            if dispatch_map:
                registered = set(dispatch_map.keys())
                source = "jaeger_agent"
                break
    except Exception:  # noqa: BLE001
        pass

    # 2) Legacy pydantic-ai agent.
    if not registered:
        try:
            from jaeger_os.main import _pipeline
            agent = _pipeline.get("agent")
            if agent is not None and hasattr(agent, "_function_toolset"):
                registered = set(agent._function_toolset.tools.keys())
                source = "pydantic_ai"
        except Exception:  # noqa: BLE001
            pass

    # 3) No agent booted.
    if not registered:
        return True, "not checked (no booted agent)"

    missing = sorted(n for n in CORE if n not in registered)
    if missing:
        return False, f"CORE tools missing from {source} registry: {missing}"
    return True, f"{len(CORE)} CORE tools resolve ({source})"


def _check_skills_loaded() -> tuple[bool, str]:
    """At least one skill is discoverable on disk. Zero skills usually
    means the instance was created but never had its scaffold synced,
    which is a confusing failure mode — the agent boots fine but says
    "I have no skills" mid-conversation."""
    from jaeger_os.agent.skill_registry.skill_loader import discover_skills
    from jaeger_os.agent.tools._common import _require_layout
    layout = _require_layout()
    try:
        skills = list(discover_skills(layout))
    except Exception as exc:  # noqa: BLE001
        return False, f"discover_skills raised: {type(exc).__name__}: {exc}"
    if not skills:
        return False, "no skills discovered under skills/"
    return True, f"{len(skills)} skill(s) discovered"


def _check_drift_parser() -> tuple[bool, str]:
    """The drift parser is the safety net for models that emit tool
    calls as raw text instead of structured calls. A regression here
    would silently degrade routing for every model that drifts — this
    check pins a canonical Gemma-style emission and confirms it
    survives parsing.

    The sample uses Gemma 4's paren-kwarg dialect wrapped in
    ``<|tool_call>…<tool_call|>`` — the form ``boot_for_tui``'s
    Gemma adapter actually emits. A bare bracketed call like
    ``[get_time(...)]`` is not a recognised dialect (Gemma never
    produces that) and would give a false negative.
    """
    from jaeger_os.agent.dialects import extract_tool_calls
    sample = '<|tool_call>call:get_time(timezone="UTC")<tool_call|>'
    try:
        calls = extract_tool_calls(sample)
    except Exception as exc:  # noqa: BLE001
        return False, f"parser raised: {type(exc).__name__}: {exc}"
    if not calls:
        return False, "parser returned no calls on canonical sample"
    name = getattr(calls[0], "name", None) or (
        calls[0].get("name") if isinstance(calls[0], dict) else None
    )
    if name != "get_time":
        return False, f"parser returned wrong tool name: {name!r}"
    return True, f"parsed {len(calls)} call(s) ok"


# ── canonical probe set ─────────────────────────────────────────────


# Order matters: layout first (failure cascades), drift_parser last
# (purely in-process, useful even when the rest of the runtime is
# wedged). The set is small enough that running it linearly is faster
# than coordinating threads.
DEFAULT_CHECKS: list[HealthCheck] = [
    HealthCheck("layout",         _check_layout),
    HealthCheck("file_sandbox",   _check_file_sandbox),
    HealthCheck("memory",         _check_memory),
    HealthCheck("time",           _check_time),
    HealthCheck("calculate",      _check_calculate),
    HealthCheck("tool_registry",  _check_tool_registry),
    HealthCheck("skills_loaded",  _check_skills_loaded),
    HealthCheck("drift_parser",   _check_drift_parser),
]


# ── runner ──────────────────────────────────────────────────────────


def _run_one(check: HealthCheck) -> HealthResult:
    """Invoke one check, time it, swallow exceptions as failures so
    the rest of the probe still runs."""
    started = time.perf_counter()
    try:
        ok, detail = check.fn()
    except Exception as exc:  # noqa: BLE001 — probe must survive bad checks
        ok = False
        detail = f"{type(exc).__name__}: {exc}"
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return HealthResult(name=check.name, ok=bool(ok), detail=detail,
                        elapsed_ms=round(elapsed_ms, 1))


def run_health_checks(
    checks: list[HealthCheck] | None = None,
    *,
    deep: bool = False,
) -> dict[str, Any]:
    """Run every check and roll up a summary dict.

    Returns ``{ok, passed, total, checks: [...], elapsed_s}``.

    ``deep=False`` (default) — the lean substrate probes only:
    layout, sandbox, memory, time, calculate, tool_registry, skills,
    drift_parser. Under 3 seconds total, idempotent, safe for cron.

    ``deep=True`` — adds the agent-loop probes (see
    :data:`DEEP_CHECKS`). These drive the LIVE agent through three
    representative turns (no-tool answer, read-only tool, sandbox
    write) so the operator can verify "the agent can actually answer
    a question" — not just "the substrate is healthy".

    ``ok`` is True only when every probe passed — strict roll-up so a
    caller can branch on the topline boolean without inspecting
    individual rows. The full results list stays in ``checks`` for
    drill-down."""
    selected = list(checks) if checks is not None else list(DEFAULT_CHECKS)
    if deep and checks is None:
        selected += DEEP_CHECKS
    started = time.perf_counter()
    results = [_run_one(c) for c in selected]
    elapsed_s = time.perf_counter() - started
    passed = sum(1 for r in results if r.ok)
    return {
        "ok": passed == len(results),
        "passed": passed,
        "total": len(results),
        "deep": bool(deep and checks is None),
        "checks": [
            {"name": r.name, "ok": r.ok, "detail": r.detail,
             "elapsed_ms": r.elapsed_ms}
            for r in results
        ],
        "elapsed_s": round(elapsed_s, 3),
    }


# ── deep checks — drive the LIVE agent loop ────────────────────────


def _check_agent_no_tool() -> tuple[bool, str]:
    """One free-text turn through the real agent. No tools required —
    proves the model loads, decodes, and produces a final answer.
    Cheap (~1-3s on a warm model)."""
    try:
        from jaeger_os.main import _pipeline, run_command
    except Exception as exc:  # noqa: BLE001
        return False, f"could not import agent: {exc}"
    client = _pipeline.get("client")
    if client is None:
        return False, "no booted client — start the TUI first"
    try:
        out = run_command(client, "Reply with one word: alive",
                          session_key="health_probe_no_tool")
    except Exception as exc:  # noqa: BLE001
        return False, f"agent raised: {type(exc).__name__}: {exc}"
    text = (out.get("text") or "").strip().lower()
    if not text:
        return False, "agent returned empty answer"
    return True, f"answered in {out.get('elapsed_s', 0):.1f}s"


def _check_agent_read_tool() -> tuple[bool, str]:
    """One turn that should route to a READ-only tool — calculate
    is the cheapest: a wrong answer is a hard fail, a right answer
    proves dispatch + the post-call finalizer."""
    try:
        from jaeger_os.main import _pipeline, run_command
    except Exception as exc:  # noqa: BLE001
        return False, f"could not import agent: {exc}"
    client = _pipeline.get("client")
    if client is None:
        return False, "no booted client"
    try:
        out = run_command(client, "calculate 7 times 6",
                          session_key="health_probe_read")
    except Exception as exc:  # noqa: BLE001
        return False, f"agent raised: {type(exc).__name__}: {exc}"
    text = (out.get("text") or "")
    if "42" not in text:
        return False, f"calculate didn't return 42: {text[:80]!r}"
    return True, f"calculate→42 in {out.get('elapsed_s', 0):.1f}s"


def _check_agent_sandbox_write() -> tuple[bool, str]:
    """One write+read round-trip through the agent. Proves the
    permission tier system isn't blocking sandboxed writes and the
    finalizer's "shortest possible reply" rule still surfaces the
    work."""
    try:
        from jaeger_os.main import _pipeline, run_command
        from jaeger_os.agent.tools._common import _require_layout
    except Exception as exc:  # noqa: BLE001
        return False, f"could not import agent: {exc}"
    client = _pipeline.get("client")
    if client is None:
        return False, "no booted client"
    probe_name = "_health_probe_write.txt"
    try:
        run_command(
            client,
            f"Write the text 'health ok' to {probe_name} and then "
            f"read it back to confirm.",
            session_key="health_probe_write",
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"agent raised: {type(exc).__name__}: {exc}"
    # Verify the file actually landed in the sandbox.
    layout = _require_layout()
    probe_path = layout.skills_dir / probe_name
    if not probe_path.is_file():
        return False, f"sandbox write did not produce {probe_path}"
    body = probe_path.read_text(encoding="utf-8")
    try:
        probe_path.unlink()
    except OSError:
        pass
    if "health ok" not in body.lower():
        return False, f"file present but content mismatch: {body[:60]!r}"
    return True, "write+read+verify ok"


# Drives the LIVE agent through three turns — substantially slower
# than the lean probes (each LLM call costs whatever the loaded
# model costs). Only fires when ``run_health_checks(deep=True)``.
DEEP_CHECKS: list[HealthCheck] = [
    HealthCheck("agent.no_tool",       _check_agent_no_tool),
    HealthCheck("agent.read_tool",     _check_agent_read_tool),
    HealthCheck("agent.sandbox_write", _check_agent_sandbox_write),
]


__all__ = [
    "DEEP_CHECKS",
    "DEFAULT_CHECKS",
    "HealthCheck",
    "HealthResult",
    "run_health_checks",
]
