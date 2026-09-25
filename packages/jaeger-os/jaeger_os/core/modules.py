"""module.yaml → validated ``ModuleSpec`` (the engine-module discovery seam).

A module directory (``jaeger_os/nodes/<name>/`` or, since 0.8 M3b,
``jaeger_os/plugins/<name>/``) holds ``module.yaml`` declaring its
slot, topics, tools, factory, and the third-party libraries its
engine needs (``requires_libraries``) — the module owns its own
readiness requirements, the same way a plugin's ``plugin.yaml`` owns
its ``requires: libraries:`` block. The loader validates STRICTLY
(unknown fields refuse, missing factory refuses, empty slot refuses)
— loudly at load time with the offending file named, never a silent
degrade. Mirrors ``jaeger_os/hardware/package.py``'s house style.

``discover_modules`` walks the immediate subdirectories of one or more
roots (default ``(NODES_DIR, PLUGINS_DIR)``) and returns every module
found across ALL roots, keyed by slot. A broken ``module.yaml`` raises
rather than being skipped — a typo in a shipped module must fail
loudly, not vanish from discovery. Most slots are one-module (the
manifest's ``slot=`` node binding picks a single factory); ``messaging``
(0.8 M3b) is the first genuinely multi-module slot — discord, telegram,
and imessage all declare ``slot: messaging`` and coexist in the same
list (ANY-OF readiness is a caller concern, see
``jaeger_os/agent/availability.py``).

NO manifest.py changes here: manifests keep explicit factory strings
for now. module.yaml is authoritative *metadata*; slot-resolution
binding (manifests picking a factory *by slot*) is a later step.

``ModuleSpec`` itself lives in ``jaeger_os.contract.modules`` (0.9 contract
package) — re-exported here unchanged so existing ``from
jaeger_os.core.modules import ModuleSpec`` call sites keep working. This
module owns the LOADER: discovery, parsing, and validation.

0.9 step 3 (mind-as-module): ``jaeger_os/agent/`` gained its own
``module.yaml`` (``slot: mind``) — but unlike ``nodes/`` and
``plugins/``, which hold MANY module subdirectories, the Mind is a
singleton and its ``module.yaml`` sits directly at ``agent/``'s own
root, not one level down. ``AGENT_DIR`` is added as a third default
discovery root, and the walk below checks whether a root *itself* is
a module (has ``module.yaml`` directly) before falling back to
scanning its children — so ``discover_modules()`` finds the mind slot
with zero special-casing at any call site.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import pathlib
import sys

import msgspec

from jaeger_os.contract.modules import MODULE_KINDS, ModuleSpec

# stdlib logging, not jaeger_os.app.logging: core/ does not import app/
# (the layering test enforces the tiers) and discovery runs at boot,
# before any bus exists to publish a LogLine on.
_log = logging.getLogger(__name__)

# The directories module.yaml files live under (or, for AGENT_DIR, IS
# one). Derived the same way (relative to this file, not cwd) so
# discovery works regardless of where the process was launched from.
# Post-0.9-split: JaegerOS's own tree no longer has kokoro_tts/
# whisper_stt/agent (they moved to their own installed packages), so
# these three roots alone are no longer the whole picture — see
# ``_external_module_roots`` below for how out-of-tree packages
# contribute their own roots without JaegerOS hardcoding their names.
NODES_DIR = pathlib.Path(__file__).resolve().parents[1] / "nodes"
PLUGINS_DIR = pathlib.Path(__file__).resolve().parents[1] / "plugins"
AGENT_DIR = pathlib.Path(__file__).resolve().parents[1] / "agent"

_MODULE_ROOTS_GROUP = "jaeger_os.module_roots"

# Applications and mind modules are different roles. JaegerAI, JP01, and
# Mochi are applications; JaegerAgent is a reusable mind they may compose.
# App-owned config/identity lookups use this explicit process-local binding.
_application_package: str | None = None

#: A project's own module directory. Anything here SHADOWS an
#: installed module claiming the same slot — ROS's workspace overlay,
#: where ``~/ws/src`` wins over ``/opt/ros``.
#:
#: The point is that nothing you are actively working on is hidden.
#: Install the common case and never look at it; the day you need to
#: change one, copy it in here and it takes over. No repo surgery, no
#: reinstall, and deleting the folder puts the installed one back.
PROJECT_MODULES_DIRNAME = "modules"


def project_module_root(project_dir) -> pathlib.Path | None:
    """``<project>/modules`` if it exists, else ``None``."""
    if project_dir is None:
        return None
    root = pathlib.Path(project_dir) / PROJECT_MODULES_DIRNAME
    return root if root.is_dir() else None


def _external_module_roots() -> tuple[pathlib.Path, ...]:
    """Roots contributed by OTHER installed packages via the
    ``jaeger_os.module_roots`` entry-point group — the out-of-tree
    loading seam (0.9 step 4 split: JaegerAI/JaegerKokoroTTS/
    JaegerWhisperSTT each ship one). JaegerOS never hardcodes those
    package names; it only knows the group name. Each entry point's
    callable takes no args and returns an iterable of directories to
    scan the same way NODES_DIR/PLUGINS_DIR/AGENT_DIR are scanned.

    Fail-soft by design: a package that isn't installed contributes
    nothing (no entry points found), and a contributor whose callable
    raises is skipped rather than aborting discovery for everyone else
    — this mirrors the existing guarded-import tolerance for optional
    engine modules (M2a/M2b), just at the package-discovery layer
    instead of the symbol-import layer. A malformed module.yaml INSIDE
    a discovered root still raises loudly once found (unchanged)."""
    roots: list[pathlib.Path] = []
    try:
        eps = importlib.metadata.entry_points(group=_MODULE_ROOTS_GROUP)
    except Exception as exc:  # noqa: BLE001 — a broken metadata index
        _log.warning(                     # shouldn't take down discovery
            "module discovery: cannot read the entry-point index (%s: %s)"
            " — no out-of-tree modules will be found",
            type(exc).__name__, exc,
        )
        return ()
    for ep in eps:
        try:
            contributed = ep.load()()
        except Exception as exc:  # noqa: BLE001 — one bad contributor,
            # not fatal for the others, but NEVER silent: an installed
            # package whose entry point raises is a broken install, and
            # before this it vanished from discovery with no symptom
            # beyond a KeyError at some unrelated call site.
            _log.warning(
                "module discovery: %r is installed but its entry point "
                "%s failed to load (%s: %s) — its modules will not be "
                "found. This is a broken install, not a missing package.",
                ep.name, ep.value, type(exc).__name__, exc,
            )
            continue
        for r in contributed:
            roots.append(pathlib.Path(r))
    return tuple(roots)


def _check_factory(factory: str, *, path: pathlib.Path) -> None:
    mod_path, _, attr = factory.partition(":")
    if not mod_path.strip() or not attr.strip():
        raise ValueError(
            f"{path}: factory {factory!r} must be 'pkg.mod:attr' form"
        )


def load_module(dir: pathlib.Path) -> ModuleSpec:
    """Parse + validate ``<dir>/module.yaml``.

    Raises ``ValueError`` naming the offending file on any schema
    violation (unknown key, missing required field, empty slot,
    malformed factory string)."""
    import yaml

    p = pathlib.Path(dir) / "module.yaml"
    if not p.is_file():
        raise FileNotFoundError(f"no module.yaml at {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    try:
        spec = msgspec.convert(raw, ModuleSpec)
    except msgspec.ValidationError as exc:
        raise ValueError(f"{p}: {exc}") from None
    if not spec.slot.strip():
        raise ValueError(f"{p}: slot must be non-empty")
    if spec.type != "module":
        raise ValueError(
            f"{p}: type {spec.type!r} must be 'module' for module.yaml"
        )
    if spec.kind and spec.kind not in MODULE_KINDS:
        # Named here rather than left to msgspec so the error points at
        # the file the operator has to fix.
        raise ValueError(
            f"{p}: kind {spec.kind!r} is not one of "
            f"{sorted(MODULE_KINDS)}"
        )
    _check_factory(spec.factory, path=p)
    return spec


def module_platform_ok(spec: ModuleSpec) -> bool:
    """True iff ``spec.requires_platform`` is empty (any platform) or
    contains the current ``sys.platform`` (prefix match, same
    convention as the plugin manifest's ``requires: platform:``)."""
    if not spec.requires_platform:
        return True
    current = sys.platform  # "darwin", "linux", "win32", ...
    return any(current.startswith(p) for p in spec.requires_platform)


def discover_modules(
    roots: pathlib.Path | tuple[pathlib.Path, ...] | None = None,
    *,
    project_dir=None,
) -> dict[str, list[ModuleSpec]]:
    """Scan one or more roots for ``module.yaml`` and return every
    module found across ALL roots, keyed by slot. Default roots:
    ``(NODES_DIR, PLUGINS_DIR, AGENT_DIR)`` PLUS whatever
    ``_external_module_roots()`` finds via the ``jaeger_os.module_roots``
    entry-point group — the out-of-tree seam other installed packages
    (JaegerAI, JaegerKokoroTTS, JaegerWhisperSTT, ...) use to surface
    their own module.yaml-bearing directories without JaegerOS ever
    naming them.

    A root is checked two ways: is the root ITSELF a module (has
    ``module.yaml`` directly — ``AGENT_DIR``'s shape, a singleton
    module with no sibling), or does it hold module SUBdirectories
    (``NODES_DIR``/``PLUGINS_DIR``'s shape, many engine/plugin
    modules). A root that's a module itself is not also scanned for
    child modules — the Mind has no nested modules to find.

    A single ``pathlib.Path`` is also accepted (normalized to a
    one-tuple) for callers/tests that only care about one directory —
    an explicit ``roots=`` argument bypasses BOTH the local defaults
    AND the external entry-point scan, same as before this change.

    Directories without a ``module.yaml`` are skipped silently (not
    every node/plugin package is a module yet). A directory *with* a
    ``module.yaml`` that fails validation raises — a broken module
    must fail loudly, not disappear from discovery. A slot can span
    multiple modules across roots (e.g. ``messaging`` — discord,
    telegram, imessage all live under ``plugins/`` and share the
    slot); callers doing ANY-OF readiness must consult every entry."""
    local_root = project_module_root(project_dir)
    if roots is None:
        roots = (NODES_DIR, PLUGINS_DIR, AGENT_DIR) + _external_module_roots()
        # LAST, so the overlay pass below sees it as the local one.
        if local_root is not None:
            roots = roots + (local_root,)
    elif isinstance(roots, (str, pathlib.Path)):
        roots = (pathlib.Path(roots),)

    by_slot: dict[str, list[ModuleSpec]] = {}
    for root in roots:
        root = pathlib.Path(root)
        if not root.is_dir():
            continue
        found = [root] if (root / "module.yaml").is_file() else [
            c for c in sorted(root.iterdir())
            if c.is_dir() and (c / "module.yaml").is_file()
        ]
        for directory in found:
            spec = load_module(directory)
            spec.source_dir = directory
            spec.local = local_root is not None and _is_within(directory, local_root)
            by_slot.setdefault(spec.slot, []).append(spec)

    return _apply_overlay(by_slot) if local_root is not None else by_slot


def _is_within(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _apply_overlay(
    by_slot: dict[str, list[ModuleSpec]],
) -> dict[str, list[ModuleSpec]]:
    """Drop installed modules from any slot a LOCAL module claims.

    Shadowing is per-SLOT, not per-module-name, because the slot is
    what the app binds. Two animation engines both answering
    ``slot = "animation"`` is ambiguity the app cannot resolve at
    runtime, and silently picking one is how you end up debugging the
    wrong copy of a file.

    Always logged. An override that takes effect without saying so is
    the hidden behaviour this feature exists to remove.
    """
    out: dict[str, list[ModuleSpec]] = {}
    for slot, specs in by_slot.items():
        local = [s for s in specs if getattr(s, "local", False)]
        if not local:
            out[slot] = specs
            continue
        shadowed = [s for s in specs if not getattr(s, "local", False)]
        for s in shadowed:
            _log.info(
                "slot %r: using LOCAL %s (shadows installed %s)",
                slot, local[0].source_dir, s.module,
            )
        if not shadowed:
            _log.info("slot %r: using LOCAL %s", slot, local[0].source_dir)
        out[slot] = local
    return out


def resolve_mind_module(suffix: str = ""):
    """Import and return a module off the installed Mind's OWN package
    ROOT (e.g. ``core.context``, ``core.instance.schemas``) — for the
    handful of framework call sites that need to read INSTANCE state
    (config, identity, active character) rather than a slot-owned
    engine symbol. Uses the ``mind`` slot's factory string (``agent/``
    ships ``module.yaml`` with ``slot: mind``) purely to learn the
    Mind's top-level package NAME (the factory dotted path's first
    component, e.g. ``jaeger_ai`` off
    ``jaeger_ai.agent.loop.mind_node:make_mind_node``) — never
    hardcoded, so this file still doesn't name ``jaeger_ai`` anywhere.
    Deliberately NOT built on :func:`resolve_slot_module` — that
    suffixes onto the factory's OWN module path (agent/...), while
    core/context.py etc. live at the Mind's package ROOT, a sibling of
    ``agent/``, not a child of it.

    Returns ``None`` if no mind module is installed (headless body —
    correct, not an error) or the suffix doesn't exist there.

    Pre-0.9-split, ``jaeger_os.core.context`` /
    ``jaeger_os.core.instance.schemas`` were nested submodules of the
    SAME package as this file, so a hardcoded dotted import worked.
    Post-split those moved to the Mind's own package (jaeger_ai today)
    — the dotted path is no longer knowable at write-time, only at
    install-time, which is exactly what this resolves."""
    try:
        by_slot = discover_modules()
        candidates = by_slot.get("mind", [])
        if not candidates:
            return None
        chosen = sorted(candidates, key=lambda m: m.module)[0]
        mod_path, _, _ = chosen.factory.partition(":")
        top = mod_path.split(".")[0]
        full = f"{top}.{suffix}" if suffix else top
        return importlib.import_module(full)
    except Exception:  # noqa: BLE001 — inert absence, not a crash
        return None


def set_application_package(package_or_factory: str | None) -> None:
    """Bind the active application's top-level package.

    Accepts either ``"jaeger_ai"`` or a manifest factory reference such as
    ``"jaeger_ai.core.agent_core:make_core"``. Passing ``None`` clears it.
    """
    global _application_package
    if package_or_factory is None:
        _application_package = None
        return
    module_path = str(package_or_factory).partition(":")[0].strip()
    package = module_path.split(".")[0]
    if not package or not package.isidentifier():
        raise ValueError(f"invalid application package/factory: {package_or_factory!r}")
    _application_package = package


def resolve_application_module(suffix: str = ""):
    """Resolve an app-owned module without conflating app and mind roles."""
    package = _application_package
    if not package:
        return None
    full = f"{package}.{suffix}" if suffix else package
    try:
        return importlib.import_module(full)
    except Exception:  # noqa: BLE001 — optional application seam
        return None


def resolve_slot_module(slot: str, suffix: str = ""):
    """Import and return the winning module's own factory-string
    module for ``slot`` (optionally one of ITS OWN submodules, via
    ``suffix``, e.g. ``"engine.registry"``) — the shared
    discovery-driven primitive that replaces a hardcoded
    ``jaeger_os.nodes.<engine>[.sub...]`` dotted import (0.9 step 4:
    kokoro_tts/whisper_stt/animation/etc. can each live in a wholly
    separate installed package post-split, so the dotted path can't be
    hardcoded anymore — see ``nodes/__init__.py``, ``nodes/runtime.py``,
    ``core/audio/session.py``, ``core/voice/voice_resolution.py``'s
    call sites).

    Ties (>1 module for the slot) resolve the same deterministic way
    ``app/app.py``'s ``_resolve_slot`` does — sorted by module name,
    first wins. Returns ``None`` on ANY failure: no module for the
    slot, a malformed module.yaml, the module's package not installed,
    or the suffix submodule doesn't exist — this is import-time
    tolerance, not the readiness gate (``agent/availability.py`` still
    owns failing the actual tool closed)."""
    try:
        by_slot = discover_modules()
        candidates = by_slot.get(slot, [])
        if not candidates:
            return None
        chosen = sorted(candidates, key=lambda m: m.module)[0]
        mod_path, _, _ = chosen.factory.partition(":")
        full_path = f"{mod_path}.{suffix}" if suffix else mod_path
        return importlib.import_module(full_path)
    except Exception:  # noqa: BLE001 — inert absence, not a crash
        return None


def resolve_slot_symbols(slot: str, names: tuple[str, ...]) -> dict:
    """Resolve ``names`` off the winning module's own factory-string
    module for ``slot`` (see :func:`resolve_slot_module`). Each name is
    tried first as an ATTRIBUTE of that module (the common case: a
    re-exported class/function), then — if absent — as one of the
    module's own direct SUBMODULES (e.g. ``nodes.runtime`` wants the
    whole ``bridge`` submodule off ``nodes.animation``, not just a
    re-exported symbol; a plain ``getattr`` only sees ``bridge`` there
    if something else already imported it first, which isn't
    guaranteed at boot). Returns ``{}`` (every name absent) if the slot
    itself can't be resolved, or per-name if a particular
    attribute/submodule is missing."""
    mod = resolve_slot_module(slot)
    if mod is None:
        return {}
    mod_path = mod.__name__
    out: dict = {}
    for n in names:
        if hasattr(mod, n):
            out[n] = getattr(mod, n)
            continue
        try:
            out[n] = importlib.import_module(f"{mod_path}.{n}")
        except ImportError:
            pass
    return out


__all__ = [
    "ModuleSpec", "load_module", "discover_modules", "module_platform_ok",
    "resolve_slot_module", "resolve_slot_symbols", "resolve_mind_module",
    "resolve_application_module", "set_application_package",
    "NODES_DIR", "PLUGINS_DIR", "AGENT_DIR",
]
