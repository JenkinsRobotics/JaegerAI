"""Core model-free health check for the agent's own surface.

    python3 -m jaeger_agent selfcheck          # human-readable report
    python3 -m jaeger_agent selfcheck --json   # machine-readable

The bench in JaegerAI answers "does the model route well?" — it needs a
live model, an instance and several minutes. This answers the cheaper,
more basic question the bench cannot even reach when something is broken:
**is the surface itself intact?**

Every check here runs in under a second with no model, no network and no
host application. They catch the failure class that is invisible until a
user hits it: a tool whose schema will not serialise, a toolset naming a
tool that no longer exists, a skill the model is offered but cannot load,
a dialect that cannot render the catalogue. None of those raise at import
— they surface mid-turn, as a provider 400 or a silently missing
capability.

This is a SANITY check, deliberately. It asserts nothing about answer
quality; that is the bench's job and the bench stays in the application.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    count: int = 0


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [
                {"name": c.name, "ok": c.ok, "detail": c.detail, "count": c.count}
                for c in self.checks
            ],
        }


#: Distribution name -> the module it actually provides, where they differ.
#: Without this the checks report a declared package as missing purely
#: because ``pip install pillow`` gives you ``import PIL``.
_DIST_TO_IMPORT = {
    "pyyaml": "yaml",
    "llama-cpp-python": "llama_cpp",
    "jaeger-os": "jaeger_os",
    "pillow": "PIL",
    "sentence-transformers": "sentence_transformers",
    "sqlite-vec": "sqlite_vec",
    "mlx-lm": "mlx_lm",
    "mlx-vlm": "mlx_vlm",
    "pyobjc-framework-vision": "Vision",
    "pyobjc-framework-quartz": "Quartz",
    "pyobjc-framework-cocoa": "Foundation",
    "duckduckgo-search": "duckduckgo_search",
}

#: Arrive through a declared dependency rather than on their own. Listing
#: them keeps the informational check honest — flagging certifi as
#: "undeclared" when requests guarantees it is noise, and noise is how a
#: report stops being read.
_TRANSITIVE = {"certifi", "pydantic", "msgspec", "urllib3", "charset_normalizer", "idna"}


def _tools() -> list[Any]:
    import jaeger_agent.tools  # noqa: F401 — registers the surface
    from jaeger_os.core.tools.tool_registry import get_tools

    return list(get_tools())


# ── the checks ─────────────────────────────────────────────────────


def _check_tools_registered() -> Check:
    tools = _tools()
    return Check(
        "tools registered",
        bool(tools),
        f"{len(tools)} tools" if tools else "NO tools registered at all",
        len(tools),
    )


def _check_tool_names_unique() -> Check:
    """A duplicate name means one implementation silently shadows the
    other, and which one wins depends on import order."""
    seen: dict[str, int] = {}
    for t in _tools():
        seen[t.name] = seen.get(t.name, 0) + 1
    dupes = {k: v for k, v in seen.items() if v > 1}
    return Check("tool names unique", not dupes, str(dupes) if dupes else "", len(dupes))


def _check_tool_names_callable_by_a_model() -> Check:
    """Providers reject tool names outside ``[A-Za-z0-9_-]``. A bad name
    fails the whole request, not just that tool."""
    bad = [
        t.name
        for t in _tools()
        if not t.name or not all(ch.isalnum() or ch in "_-" for ch in t.name)
    ]
    return Check("tool names wire-safe", not bad, ", ".join(bad[:5]), len(bad))


def _check_tool_descriptions() -> Check:
    """An undescribed tool is one the model cannot choose on purpose."""
    bad = [t.name for t in _tools() if not (t.description or "").strip()]
    return Check("tools described", not bad, ", ".join(bad[:5]), len(bad))


def _check_schemas_serialise() -> Check:
    """The schema is what actually goes on the wire. A tool whose schema
    cannot be built or JSON-encoded takes down every turn that offers
    it — and it does so at call time, not at import."""
    bad: list[str] = []
    for t in _tools():
        try:
            json.dumps(t.to_openai_schema())
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{t.name}: {type(exc).__name__}")
    return Check("schemas serialise", not bad, "; ".join(bad[:5]), len(bad))


def _check_tools_dispatchable() -> Check:
    """Registered but not callable means the model can select it and the
    turn dies on dispatch."""
    bad = [t.name for t in _tools() if not callable(getattr(t, "fn", None))]
    return Check("tools dispatchable", not bad, ", ".join(bad[:5]), len(bad))


def _check_toolsets_resolve() -> Check:
    """INFORMATIONAL — never fails.

    A toolset may legitimately name a tool this install does not have: an
    engine module (``play_timeline``), the host application
    (``diagnostics``), a plugin (``generate_image_fal``), or an MCP
    server connected at runtime. The mind cannot tell "not installed"
    from "does not exist", so it must not fail on either.

    It is still worth printing. A name that no host ever fills is a
    toolset advertising a capability nobody provides, and this line is
    the only place that becomes visible without a live host.
    """
    from jaeger_agent.schemas.tool_bundles import JAEGER_TOOLSETS

    live = {t.name for t in _tools()}
    gaps: dict[str, list[str]] = {}
    for name, spec in JAEGER_TOOLSETS.items():
        missing = [t for t in (spec.get("tools") or []) if t not in live]
        if missing:
            gaps[name] = missing
    detail = (
        "none — every named tool is registered locally"
        if not gaps
        else "host/MCP-provided or absent: "
        + "; ".join(f"{k} -> {v[:3]}" for k, v in sorted(gaps.items()))
    )
    return Check("toolsets resolve (info)", True, detail, len(gaps))


def _check_toolsets_are_not_empty() -> Check:
    """A toolset declaring NO tools at all can only ever be dead weight
    in the catalogue the model reads."""
    from jaeger_agent.schemas.tool_bundles import JAEGER_TOOLSETS

    empty = [
        n
        for n, spec in JAEGER_TOOLSETS.items()
        if not (spec.get("tools") or spec.get("includes"))
    ]
    return Check("toolsets non-empty", not empty, ", ".join(empty[:5]), len(empty))


def _check_toolset_includes_exist() -> Check:
    """An ``includes`` naming a toolset that does not exist silently
    yields an empty bundle."""
    from jaeger_agent.schemas.tool_bundles import JAEGER_TOOLSETS

    bad: list[str] = []
    for name, spec in JAEGER_TOOLSETS.items():
        for inc in spec.get("includes") or []:
            if inc not in JAEGER_TOOLSETS:
                bad.append(f"{name} includes {inc!r}")
    return Check("toolset includes exist", not bad, "; ".join(bad[:5]), len(bad))


def _check_default_bundle_non_empty() -> Check:
    """The bundle most turns actually run on."""
    from jaeger_agent.schemas.tool_bundles import resolve_toolsets

    try:
        got = resolve_toolsets(["default"])
    except Exception as exc:  # noqa: BLE001
        return Check("default bundle resolves", False, f"{type(exc).__name__}: {exc}")
    return Check("default bundle resolves", bool(got), f"{len(got)} tools", len(got))


def _check_skills_load() -> Check:
    from jaeger_agent.skill_registry import playbook_skills as pb

    try:
        skills = pb.available_playbooks()
    except Exception as exc:  # noqa: BLE001
        return Check("skills load", False, f"{type(exc).__name__}: {exc}")
    return Check("skills load", bool(skills), f"{len(skills)} skills", len(skills))


def _check_skill_names_unique() -> Check:
    """``use_skill``'s enum is built from these names. A duplicate makes
    one of them unreachable."""
    from jaeger_agent.skill_registry import playbook_skills as pb

    try:
        names = [s.name for s in pb.available_playbooks()]
    except Exception as exc:  # noqa: BLE001
        return Check("skill names unique", False, f"{type(exc).__name__}: {exc}")
    dupes = {n for n in names if names.count(n) > 1}
    return Check("skill names unique", not dupes, ", ".join(sorted(dupes)[:5]), len(dupes))


def _check_use_skill_offers_only_real_skills() -> Check:
    """The Skill Enum Gate: every name the model is offered must resolve.
    An offered-but-missing skill is a guaranteed dead end mid-turn."""
    from jaeger_agent.skill_registry import playbook_skills as pb

    try:
        offered = [s.name for s in pb.available_playbooks()]
        bad = [n for n in offered if pb.find_playbook(n) is None]
    except Exception as exc:  # noqa: BLE001
        return Check("use_skill enum is honest", False, f"{type(exc).__name__}: {exc}")
    return Check("use_skill enum is honest", not bad, ", ".join(bad[:5]), len(bad))


def _check_skills_declare_real_tools() -> Check:
    """INFORMATIONAL — skills whose ``requires_tools`` name something this
    install does not have.

    Same shape as the toolset check: a skill may legitimately need a tool
    the HOST provides (``computer_do``, ``generate_image_fal``,
    ``send_message``, ``delegate_task``), so this cannot fail on a bare
    module. It is worth printing because ``use_skill`` warns the model
    when a skill's tools are missing, and a skill that will always warn
    is one the model will always avoid.
    """
    import re as _re

    import yaml as _yaml

    live = {t.name for t in _tools()}
    root = pathlib.Path(__file__).resolve().parent.parent / "skills"
    gaps: dict[str, list[str]] = {}
    for f in root.rglob("SKILL.md"):
        head = _re.match(r"^---\n(.*?)\n---", f.read_text(), _re.S)
        if not head:
            continue
        try:
            meta = _yaml.safe_load(head.group(1)) or {}
        except Exception:  # noqa: BLE001 — a malformed skill is its own problem
            continue
        missing = [t for t in (meta.get("requires_tools") or []) if t not in live]
        if missing:
            gaps[str(meta.get("name") or f.parent.name)] = missing
    detail = (
        "none — every declared tool is registered locally"
        if not gaps
        else f"{len(gaps)} skill(s) need host-provided tools: "
        + ", ".join(sorted(gaps)[:6])
    )
    return Check("skills declare real tools (info)", True, detail, len(gaps))


def _check_dialects_render() -> Check:
    """Text-dialect families render the tool catalogue into the prompt.
    A dialect that raises breaks every turn on that model family."""
    from jaeger_agent.dialects.chatml import render_tools

    tools = _tools()[:20]
    try:
        out = render_tools(tools)
    except Exception as exc:  # noqa: BLE001
        return Check("dialects render", False, f"chatml: {type(exc).__name__}: {exc}")
    return Check("dialects render", bool(out), f"{len(out)} chars", len(out))


def _check_adapters_import() -> Check:
    """Optional provider SDKs stay unimported until used, but the adapter
    MODULES must always import — they are what the bridge selects on."""
    import importlib

    bad: list[str] = []
    for mod in ("base", "local_llama", "openai", "anthropic", "mlx", "hermes_xml"):
        try:
            importlib.import_module(f"jaeger_agent.adapters.{mod}")
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{mod}: {type(exc).__name__}")
    return Check("adapters import", not bad, "; ".join(bad), len(bad))


def _check_prompt_fragments_enumerable() -> Check:
    """The Declared Fragment Registry: nothing reaches the model that is
    not a named fragment. If the registry cannot be walked, that promise
    is unverifiable."""
    from jaeger_agent.prompts.assemble import PROMPT_FRAGMENTS

    bad = [
        getattr(f, "name", "?")
        for f in PROMPT_FRAGMENTS
        if not getattr(f, "name", "") or not getattr(f, "kind", "")
    ]
    return Check(
        "prompt fragments declared",
        not bad and bool(PROMPT_FRAGMENTS),
        ", ".join(bad[:5]),
        len(PROMPT_FRAGMENTS),
    )


def _check_declared_dependencies_import() -> Check:
    """Every REQUIRED dependency must actually import.

    Added after a bench run failed on ``croniter``: scheduling imports it
    at call time, it was undeclared and absent, so ``schedule_prompt``
    errored mid-turn. The agent diagnosed it correctly — it tried to
    install the package — but that is a very expensive way to learn that
    a dependency is missing, and it only surfaced because a benchmark
    happened to exercise that tool.
    """
    import importlib.util
    import tomllib

    root = pathlib.Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        declared = tomllib.loads(root.read_text())["project"]["dependencies"]
    except Exception as exc:  # noqa: BLE001 — installed without the source tree
        return Check("declared deps import", True, f"pyproject unreadable ({type(exc).__name__})")

    aliases = _DIST_TO_IMPORT
    missing = []
    for req in declared:
        name = re.split(r"[<>=!~\[]", req)[0].strip().lower()
        mod = aliases.get(name, name.replace("-", "_"))
        if importlib.util.find_spec(mod) is None:
            missing.append(f"{name} (import {mod})")
    return Check("declared deps import", not missing, ", ".join(missing), len(missing))


def _check_runtime_imports_are_declared() -> Check:
    """INFORMATIONAL — third-party imports in package code with no
    declaration behind them.

    Not a failure: some are genuinely optional (provider SDKs behind
    extras) and some arrive transitively. But an undeclared import is a
    tool that works on the developer's machine and raises on a clean
    install, so the list is worth seeing.
    """
    import sys as _sys
    import tomllib

    root = pathlib.Path(__file__).resolve().parents[2]
    try:
        proj = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    except Exception:  # noqa: BLE001
        return Check("runtime imports declared (info)", True, "pyproject unreadable")

    known = {"jaeger_agent"} | set(_TRANSITIVE)
    reqs = list(proj.get("dependencies", []))
    for group in (proj.get("optional-dependencies") or {}).values():
        reqs.extend(group)
    for req in reqs:
        dist = re.split(r"[<>=!~\[]", req)[0].strip().lower()
        known.add(_DIST_TO_IMPORT.get(dist, dist.replace("-", "_")))

    stdlib = set(_sys.stdlib_module_names)
    undeclared: set[str] = set()
    for f in (root / "jaeger_agent").rglob("*.py"):
        if "/skills/" in str(f):
            continue                      # skill payloads carry their own deps
        try:
            tree = ast.parse(f.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                mods = [node.module or ""]
            else:
                continue
            for m in mods:
                head = m.split(".")[0]
                if head and head not in stdlib and head not in known:
                    undeclared.add(head)
    detail = ", ".join(sorted(undeclared)[:12]) if undeclared else "none"
    return Check("runtime imports declared (info)", True, detail, len(undeclared))


CHECKS = (
    _check_tools_registered,
    _check_tool_names_unique,
    _check_tool_names_callable_by_a_model,
    _check_tool_descriptions,
    _check_schemas_serialise,
    _check_tools_dispatchable,
    _check_toolsets_resolve,
    _check_toolsets_are_not_empty,
    _check_toolset_includes_exist,
    _check_default_bundle_non_empty,
    _check_skills_load,
    _check_skill_names_unique,
    _check_use_skill_offers_only_real_skills,
    _check_skills_declare_real_tools,
    _check_dialects_render,
    _check_adapters_import,
    _check_prompt_fragments_enumerable,
    _check_declared_dependencies_import,
    _check_runtime_imports_are_declared,
)


def run() -> Report:
    """Run every check. A check that raises is a FAILED check, never an
    exception out of here — a health check that dies is useless."""
    report = Report()
    for fn in CHECKS:
        try:
            report.checks.append(fn())
        except Exception as exc:  # noqa: BLE001
            name = fn.__name__.removeprefix("_check_").replace("_", " ")
            report.checks.append(Check(name, False, f"{type(exc).__name__}: {exc}"))
    return report


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    report = run()
    if "--json" in argv:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        width = max(len(c.name) for c in report.checks)
        for c in report.checks:
            mark = "ok  " if c.ok else "FAIL"
            extra = f"  {c.detail}" if c.detail else ""
            print(f"  [{mark}] {c.name:<{width}}{extra}")
        print()
        if report.ok:
            print(f"all {len(report.checks)} checks passed")
        else:
            print(f"{len(report.failures)} of {len(report.checks)} checks FAILED")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
