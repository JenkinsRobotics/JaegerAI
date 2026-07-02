"""Skill discovery and resolution.

A *skill* is a self-contained directory:

    skills/<name>_v<N>/
        SKILL.md            # When + how to use this skill
        <python module>     # Implementation
        tests/
            smoke_test.py   # Decides whether the skill is safe to register

0.3.0: a parallel canonical form lives alongside legacy
``<name>_v<N>/`` folders — see ``dev/docs/skill_schema_v3.md``:

    skills/<id>/
        manifest.yaml       # canonical v3 manifest (id, version, package,
                            #   runtime, capabilities, permissions, …)
        <python module>     # if package=code_skill
        tests/
            smoke_test.py
            benchmark.py    # optional capability scorer

The loader handles both shapes uniformly: legacy folders get a v3
``Manifest`` *synthesised* at discovery time so downstream code
(audit, scoring, the eventual marketplace) only ever sees v3 data.

The loader scans two zones:

  1. Core skills        — jaeger_os/skills/   (read-only, shipped with the framework)
  2. Instance skills    — <instance_dir>/skills/  (agent-writable, per-instance)

Resolution rules:

  - On name collision, **instance wins over core**.
  - Within a zone, the highest version wins (semver for v3 manifests;
    integer ``_v<N>`` for legacy folders, treated as ``0.<N>.0``).
  - A skill whose smoke test fails is *skipped*, not registered, and the
    failure goes into logs/audit.log so the human can see why.

Skill modules are imported via importlib and are expected to expose a
top-level callable named `register(agent)` that registers one or more
PydanticAI tools onto the agent. The loader never imports a `.py` from
outside the two zones — the path is computed from the discovered folder.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from jaeger_os.core.instance.instance import InstanceLayout
from jaeger_os.agent.skill_registry.manifest_v3 import (
    Manifest,
    ManifestError,
    legacy_stub_manifest,
    load_manifest_from_folder,
)


# Core skills shipped with the framework. Was `base_skills/` before the
# M3.5 rename; the new name matches `<instance_dir>/skills/` for symmetry
# (same word, different zone).
# core/skills/ lives two levels deeper than the framework root, so reach up two.
CORE_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "agent" / "skills"


_SKILL_RE = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9_]*)_v(?P<v>\d+)$")
# (V3 ID validation lives in jaeger_os.agent.skill_registry.manifest_v3 now.)


def _semver_tuple(v: str) -> tuple[int, ...]:
    """Crude semver sort key; non-int parts become 0.  Good enough
    for the highest-version-wins resolution rule."""
    out: list[int] = []
    for part in v.split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out)


@dataclass(frozen=True)
class DiscoveredSkill:
    name: str
    version: int
    zone: str            # "core" or "instance"
    folder: Path
    module_path: Path    # the .py file we'll import
    has_smoke: bool
    manifest: Manifest   # v3 manifest (parsed from disk OR stubbed for legacy)
    is_legacy_stub: bool # True when manifest was synthesised, not read

    @property
    def version_str(self) -> str:
        """The version as a semver string — uses the manifest's value
        so v3 skills get their real semver, legacy gets ``0.<N>.0``."""
        return self.manifest.version

    @property
    def supported(self) -> bool:
        """True iff the manifest's package + runtime are implemented in
        this loader release.  Reserved enums are accepted at parse
        time but rejected for registration."""
        return self.manifest.is_supported_package and self.manifest.is_supported_runtime


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def _scan_zone(root: Path, zone: str) -> list[DiscoveredSkill]:
    """Discover every loadable code-skill folder under ``root``.

    Two folder shapes are recognised:

      * ``<id>/`` with a ``manifest.yaml`` or v3-frontmatter
        ``SKILL.md`` — the canonical 0.3.0 shape.  Folder basename
        must match the manifest's ``id`` (validated by the parser).

      * ``<name>_v<N>/`` — legacy.  Loaded for backwards-compat; a
        v3 ``Manifest`` is synthesised at discovery time so downstream
        code never sees a legacy-only shape.

    Returns one ``DiscoveredSkill`` per folder; the loader does
    highest-version + instance-wins resolution downstream.
    """
    found: list[DiscoveredSkill] = []
    if not root.exists():
        return found
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        # Skip hidden / non-skill dirs (e.g. ``__pycache__``).
        if child.name.startswith(("_", ".")):
            continue

        legacy_match = _SKILL_RE.match(child.name)

        # Try v3 canonical first — a folder can carry BOTH manifest.yaml
        # and a legacy _v<N> name; the manifest wins.
        try:
            manifest = load_manifest_from_folder(child)
        except ManifestError as exc:
            # A broken v3 manifest is loud — operator typo'd a schema
            # field.  Don't silently fall through to legacy stub.
            print(f"[jaeger-skills] {child.name}: v3 manifest invalid, "
                  f"skipping: {exc}", flush=True)
            continue

        if manifest is not None:
            # Playbook packages have no Python module — they're handled
            # by ``playbook_skills.discover_playbooks``, not this loader.
            # Drop them out of the code-skill discovery list so the
            # registration loop below never tries to import a
            # markdown file as Python.  ``playbook_skills.discover``
            # already enumerates them on its own; this loader's job is
            # the code-skill subset.
            if manifest.package == "playbook":
                continue

            # Prefer the manifest's declared entrypoint — that's the
            # operator's source of truth.  Fall back to the file-name
            # heuristic only when the manifest didn't declare a module
            # (e.g. legacy stub or partially-ported v3).
            module: Path | None = None
            if (
                manifest.entrypoint is not None
                and manifest.entrypoint.module
            ):
                declared = child / f"{manifest.entrypoint.module}.py"
                if declared.exists():
                    module = declared
                else:
                    print(f"[jaeger-skills] {child.name}: manifest "
                          f"entrypoint.module={manifest.entrypoint.module!r} "
                          f"points at a missing file ({declared.name}); "
                          "falling back to filename heuristic",
                          flush=True)
            if module is None:
                module = _pick_module_file(child, hint=manifest.id)
            if module is None and manifest.package == "code_skill":
                print(f"[jaeger-skills] {child.name}: code_skill manifest "
                      "but no importable module file, skipping",
                      flush=True)
                continue
            found.append(DiscoveredSkill(
                name=manifest.id,
                version=_legacy_version_int(manifest.version),
                zone=zone,
                folder=child,
                module_path=module or (child / "SKILL.md"),
                has_smoke=(child / "tests" / "smoke_test.py").exists(),
                manifest=manifest,
                is_legacy_stub=False,
            ))
            continue

        # Fall through to legacy ``<name>_v<N>/`` shape.
        if legacy_match is None:
            # A directory with no v3 manifest AND no legacy version
            # suffix isn't a code skill — leave it for playbook discovery.
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.exists():
            # Half-finished folder — skip silently.
            continue
        module = _pick_module_file(child)
        if module is None:
            continue

        legacy_name = legacy_match.group("name")
        legacy_v = int(legacy_match.group("v"))
        try:
            stub = legacy_stub_manifest(
                folder=child,
                name=legacy_name,
                version=legacy_v,
                description=_legacy_description(skill_md),
                tier=_legacy_tier(skill_md),
                smoke_path=(child / "tests" / "smoke_test.py")
                           if (child / "tests" / "smoke_test.py").exists()
                           else None,
                entrypoint_module=module.stem,
            )
        except ManifestError as exc:
            print(f"[jaeger-skills] {child.name}: couldn't synthesize v3 "
                  f"stub, skipping: {exc}", flush=True)
            continue

        found.append(DiscoveredSkill(
            name=legacy_name,
            version=legacy_v,
            zone=zone,
            folder=child,
            module_path=module,
            has_smoke=(child / "tests" / "smoke_test.py").exists(),
            manifest=stub,
            is_legacy_stub=True,
        ))
    return found


def _legacy_version_int(semver: str) -> int:
    """Convert ``0.<N>.0`` (stub form) or real semver to the integer
    key the legacy ``DiscoveredSkill.version`` field expects.  Used
    for highest-version-wins ordering when comparing a v3 skill against
    a legacy ``_v<N>`` sibling on the same id."""
    try:
        return int(semver.split(".")[0]) * 10000 + int(semver.split(".")[1]) * 100 + int(semver.split(".")[2])
    except (ValueError, IndexError):
        return 0


def _legacy_description(skill_md: Path) -> str | None:
    """Pull the ``description:`` line from a legacy SKILL.md so the
    stub manifest carries something useful.  Best-effort."""
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.strip().lower().startswith("description:"):
            desc = line.split(":", 1)[1].strip().strip('"').strip("'")
            return desc or None
    return None


def _legacy_tier(skill_md: Path) -> int:
    """Pull ``permission_tier:`` from a legacy SKILL.md; default 0."""
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return 0
    for line in text.splitlines():
        if line.strip().lower().startswith("permission_tier:"):
            raw = line.split(":", 1)[1].strip().split("#", 1)[0].strip()
            try:
                tier = int(raw)
                if 0 <= tier <= 5:
                    return tier
            except ValueError:
                pass
    return 0


def _pick_module_file(folder: Path, *, hint: str | None = None) -> Path | None:
    """A skill folder may contain multiple files; the import target is
    one of (in order): <hint>.py, <name without version>.py, skill.py,
    __init__.py.  ``hint`` is the v3 manifest's ``id`` for canonical
    folders; legacy ``<name>_v<N>`` folders fall back to the regex
    match.  ``None`` when nothing importable lives in the folder
    (valid for playbook packages; rejected upstream for code_skill)."""
    candidates: list[Path] = []
    if hint:
        candidates.append(folder / f"{hint}.py")
    base = _SKILL_RE.match(folder.name)
    if base:
        candidates.append(folder / f"{base.group('name')}.py")
    candidates.append(folder / "skill.py")
    candidates.append(folder / "__init__.py")
    seen: set[Path] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        if c.exists():
            return c
    return None


def discover_skills(layout: InstanceLayout) -> list[DiscoveredSkill]:
    """Return the resolved skill set: highest-version-per-name, instance
    winning over core on name collision.  Versions are compared as
    semver tuples — a v3 manifest declaring ``2.1.0`` beats a legacy
    ``<name>_v2/`` folder declaring ``0.2.0``, which is what we want
    when both are present during the migration window."""
    core = _scan_zone(CORE_SKILLS_DIR, "core")
    instance = _scan_zone(layout.skills_dir, "instance")

    def best_in(seq: Iterable[DiscoveredSkill]) -> dict[str, DiscoveredSkill]:
        out: dict[str, DiscoveredSkill] = {}
        for s in seq:
            cur = out.get(s.name)
            if cur is None or _semver_tuple(s.version_str) > _semver_tuple(cur.version_str):
                out[s.name] = s
        return out

    core_best = best_in(core)
    instance_best = best_in(instance)
    # Instance wins on collision.
    merged = {**core_best, **instance_best}
    return sorted(merged.values(), key=lambda s: (s.zone != "instance", s.name))


# ---------------------------------------------------------------------------
# Smoke test gating
# ---------------------------------------------------------------------------
def _run_smoke(skill: DiscoveredSkill, timeout_s: float = 10.0) -> tuple[bool, str]:
    test = skill.folder / "tests" / "smoke_test.py"
    if not test.exists():
        return True, ""  # no test → trust by default (M2 will require trusted tests)
    try:
        proc = subprocess.run(
            [sys.executable, str(test)],
            capture_output=True, text=True, timeout=timeout_s,
            cwd=str(skill.folder),
        )
    except subprocess.TimeoutExpired:
        return False, f"smoke test timed out after {timeout_s}s"
    except Exception as exc:
        return False, f"smoke test couldn't run: {exc}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        return False, f"smoke test exit={proc.returncode}\n{tail}"
    return True, ""


# ---------------------------------------------------------------------------
# Import + registration
# ---------------------------------------------------------------------------
def _import_skill(skill: DiscoveredSkill) -> Any:
    mod_name = f"_jaeger_skill_{skill.zone}_{skill.name}_v{skill.version}"
    spec = importlib.util.spec_from_file_location(mod_name, skill.module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not build import spec for {skill.module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class SkillLoadReport:
    registered: list[DiscoveredSkill]
    skipped: list[tuple[DiscoveredSkill, str]]


_REGISTERED_KEYS: set[tuple[str, int, str]] = set()


def reset_registered() -> None:
    """Drop the loader's idempotency cache. Used by tests that bind/unbind
    an instance several times without restarting the process."""
    _REGISTERED_KEYS.clear()


class _ToolCapturingAgent:
    """Wraps the agent during a skill's ``register()`` so we record
    exactly which tools the skill adds — that captured set IS the
    skill's toolset (a skill is a self-describing bundle of tools).
    Every other attribute passes straight through to the real agent.

    Phase-6.2 cutover: ``tool_plain`` and ``tool`` no longer write to
    the pydantic-ai agent — they write into
    :mod:`jaeger_os.agent.schemas.tool_registry` via
    :func:`register_tool_from_function`. The wrapped ``self._agent`` is
    still used for non-tool attribute pass-through (skill code that
    reads ``agent.model``, etc.). The skill source stays unchanged —
    ``@agent.tool_plain`` still does the right thing, just into the
    new registry."""

    def __init__(self, agent: Any) -> None:
        self._agent = agent
        self.captured: list[str] = []

    def _register(
        self, fn: Callable[..., Any], **kwargs: Any,
    ) -> Callable[..., Any]:
        """Lift one skill function into the framework-free registry.
        Captures the name so the skill becomes its own named toolset."""
        from jaeger_os.agent.schemas.tool_registry import register_tool_from_function
        name = getattr(fn, "__name__", None)
        if name:
            self.captured.append(name)
        # ``register_tool_from_function`` synthesizes the args model from
        # the function signature — works for the vast majority of skill
        # tools, which use plain type hints. Skills that need a custom
        # args model can call ``register_tool_instance`` directly.
        register_tool_from_function(fn, **kwargs)
        return fn

    def _wrap(self, _legacy_real: Callable[..., Any] | None) -> Callable[..., Any]:
        def deco(*args: Any, **kwargs: Any) -> Any:
            # Bare-decorator form: @agent.tool_plain  → args == (fn,)
            if len(args) == 1 and not kwargs and callable(args[0]):
                return self._register(args[0])
            # Parametrised form: @agent.tool_plain(retries=…) returns a
            # decorator. Honour the kwargs that map to our decorator's
            # surface (``name`` / ``description``); silently drop the
            # pydantic-ai-specific knobs (``retries``) since the new
            # loop owns retry semantics.
            our_kwargs: dict[str, Any] = {}
            for k in ("name", "description"):
                if k in kwargs:
                    our_kwargs[k] = kwargs[k]
            def capture_parametrized(fn: Callable[..., Any]) -> Any:
                return self._register(fn, **our_kwargs)
            return capture_parametrized
        return deco

    @property
    def tool_plain(self) -> Callable[..., Any]:
        return self._wrap(None)

    @property
    def tool(self) -> Callable[..., Any]:
        return self._wrap(None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._agent, name)


def _skill_summary(skill: DiscoveredSkill) -> str:
    """One-line summary for the toolset catalog — the SKILL.md
    ``description:`` field, else a generic fallback."""
    try:
        md = (skill.module_path.parent / "SKILL.md").read_text(encoding="utf-8")
    except Exception:
        return f"the {skill.name} skill"
    for line in md.splitlines():
        if line.strip().lower().startswith("description:"):
            desc = line.split(":", 1)[1].strip()
            if desc:
                return desc
    return f"the {skill.name} skill"


def load_and_register(
    agent: Any,
    layout: InstanceLayout,
    *,
    run_smoke_tests: bool = True,
    enabled_allowlist: list[str] | None = None,
    audit: Callable[[str, dict[str, Any]], None] | None = None,
) -> SkillLoadReport:
    """Discover skills, gate on smoke tests, register passers onto the agent.

    `enabled_allowlist` (from config.skills.enabled_base_skills) filters
    *core* skills only — instance skills are always considered. Empty list
    or None disables the filter.
    `audit` is the audit-log callback (so skips are visible in logs/audit.log).
    """
    registered: list[DiscoveredSkill] = []
    skipped: list[tuple[DiscoveredSkill, str]] = []

    for skill in discover_skills(layout):
        key = (skill.name, skill.version, skill.zone)
        if key in _REGISTERED_KEYS:
            # Already wired during a prior call — skipping is the correct
            # behavior for hot-reload (pydantic-ai's @tool_plain raises if
            # we try to register the same name twice).
            continue

        if (
            skill.zone == "core"
            and enabled_allowlist
            and skill.name not in enabled_allowlist
        ):
            skipped.append((skill, "disabled by config"))
            if audit:
                audit("skill_skip", {"skill": skill.name, "version": skill.version,
                                     "zone": skill.zone, "reason": "disabled_by_config"})
            continue

        # 0.3.0: reject manifests declaring reserved-but-not-implemented
        # ``package`` / ``runtime`` enums.  Parsing accepts them so
        # forward-looking skills can write a real manifest now; the
        # loader will pick them up automatically when 0.4.x adds the
        # corresponding adapter.
        if not skill.supported:
            reason = (
                f"package={skill.manifest.package!r} / "
                f"runtime={skill.manifest.runtime!r} not implemented yet"
            )
            skipped.append((skill, reason))
            if audit:
                audit("skill_unsupported", {
                    "skill": skill.name, "version": skill.version_str,
                    "zone": skill.zone, "package": skill.manifest.package,
                    "runtime": skill.manifest.runtime,
                })
            continue

        # Legacy stub heads-up — not an error; surfaces in audit so the
        # operator sees which skills still need real v3 manifests.
        if skill.is_legacy_stub and audit:
            audit("skill_legacy_stub", {
                "skill": skill.name, "version": skill.version_str,
                "zone": skill.zone, "folder": str(skill.folder),
            })

        if run_smoke_tests and skill.has_smoke:
            ok, msg = _run_smoke(skill)
            if not ok:
                skipped.append((skill, msg))
                if audit:
                    audit("skill_smoke_fail", {"skill": skill.name, "version": skill.version,
                                                "zone": skill.zone, "error": msg[:500]})
                print(f"[jaeger-skills] {skill.name}_v{skill.version} ({skill.zone}) skipped: smoke test failed.",
                      flush=True)
                continue
        elif run_smoke_tests and not skill.has_smoke and skill.zone != "core":
            # Marketplace + agent-authored code skills MUST ship a
            # smoke test. "No smoke means pass" stays only for core
            # (shipped, trusted) skills; an instance-zone skill
            # without ``tests/smoke_test.py`` is half-finished and
            # not safe to auto-register. The user can still load it
            # manually after authoring a smoke test.
            reason = ("instance-zone skill has no tests/smoke_test.py — "
                      "required for non-core code skills")
            skipped.append((skill, reason))
            if audit:
                audit("skill_smoke_missing", {
                    "skill": skill.name, "version": skill.version,
                    "zone": skill.zone,
                })
            print(f"[jaeger-skills] {skill.name}_v{skill.version} "
                  f"({skill.zone}) skipped: missing smoke test "
                  f"(non-core skills must ship tests/smoke_test.py).",
                  flush=True)
            continue

        # Safety scan — a static content scan (exfiltration, prompt
        # injection, destructive commands, embedded secrets). A `danger`
        # verdict blocks an instance-zone skill before its Python is
        # imported; a core/shipped skill is only warned about.
        try:
            from jaeger_os.core.safety.skills_guard import scan_skill
            scan = scan_skill(skill.folder, name=skill.name)
        except Exception:  # noqa: BLE001
            scan = None
        if scan is not None and scan.is_danger:
            if audit:
                audit("skill_guard_flag", {
                    "skill": skill.name, "version": skill.version,
                    "zone": skill.zone, "verdict": scan.verdict,
                    "findings": len(scan.findings),
                })
            if skill.zone != "core":
                skipped.append((skill, f"safety scan: {scan.verdict}"))
                print(f"[jaeger-skills] {skill.name}_v{skill.version} "
                      f"({skill.zone}) skipped: safety scan flagged "
                      f"{len(scan.findings)} issue(s).", flush=True)
                continue
            print(f"[jaeger-skills] WARNING: core skill {skill.name} "
                  f"tripped the safety scan ({len(scan.findings)} "
                  "finding(s)) — loading anyway (shipped/trusted).",
                  flush=True)

        try:
            module = _import_skill(skill)
            # 0.3.0: prefer the manifest's declared entrypoint attr.
            # Legacy stubs always say ``attr: register``; v3 manifests
            # can declare any callable name, so a skill whose entry
            # point isn't literally ``register`` is loadable.
            entry_attr = "register"
            if (
                skill.manifest.entrypoint is not None
                and skill.manifest.entrypoint.attr
            ):
                entry_attr = skill.manifest.entrypoint.attr
            register = getattr(module, entry_attr, None)
            if register is None:
                skipped.append((skill,
                                f"no {entry_attr}(agent) callable in module"))
                continue
            # Register through a capturing wrapper so the skill's tools
            # become its own named toolset (a skill IS a toolset).
            capturing = _ToolCapturingAgent(agent)
            register(capturing)
            if capturing.captured:
                try:
                    from jaeger_os.agent.skill_registry.toolset_scoping import register_skill_toolset
                    register_skill_toolset(skill.name, capturing.captured,
                                           summary=_skill_summary(skill))
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:
            tb = traceback.format_exc(limit=4)
            skipped.append((skill, f"import/register failed: {exc}\n{tb}"))
            if audit:
                audit("skill_register_fail", {"skill": skill.name, "version": skill.version,
                                              "zone": skill.zone, "error": str(exc)})
            print(f"[jaeger-skills] {skill.name}_v{skill.version} ({skill.zone}) skipped: {exc}",
                  flush=True)
            continue

        registered.append(skill)
        _REGISTERED_KEYS.add(key)
        if audit:
            audit("skill_registered", {"skill": skill.name, "version": skill.version,
                                        "zone": skill.zone})

    if registered:
        names = ", ".join(
            f"{s.name}@{s.version_str}({s.zone})" for s in registered
        )
        print(f"[jaeger-skills] registered {len(registered)} tool-skill(s): {names}", flush=True)
        stub_count = sum(1 for s in registered if s.is_legacy_stub)
        if stub_count:
            print(
                f"[jaeger-skills] {stub_count} of those still use a legacy "
                "<name>_v<N>/ folder — port them to manifest.yaml at your "
                "convenience (dev/docs/skill_schema_v3.md).",
                flush=True,
            )
    # Playbook skills (procedural SKILL.md docs the agent reads on
    # demand via the ``skill`` tool) live alongside the tool-skills but
    # are NOT registered as agent tools — they get discovered + indexed
    # separately. Mention the count here so the operator sees the full
    # surface, not just the Python-module slice.
    pb_count = 0
    try:
        from jaeger_os.agent.skill_registry.playbook_skills import discover_playbooks
        pb_count = len(discover_playbooks())
        if pb_count:
            print(f"[jaeger-skills] {pb_count} playbook skill(s) available "
                  f"via the ``skill`` tool (action=list/view).", flush=True)
    except Exception:  # noqa: BLE001 — playbook discovery must not block boot
        pass
    # The full agentic surface in one line: raw tools + tool-skills + playbooks.
    try:
        from jaeger_os.agent.schemas.tool_registry import get_tools
        print(f"[jaeger-skills] agentic surface: {len(get_tools())} tools · "
              f"{len(registered)} tool-skill(s) · {pb_count} playbook skill(s).",
              flush=True)
    except Exception:  # noqa: BLE001
        pass
    return SkillLoadReport(registered=registered, skipped=skipped)
