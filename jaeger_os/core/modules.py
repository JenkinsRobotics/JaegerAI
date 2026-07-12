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
"""

from __future__ import annotations

import pathlib
import sys

import msgspec

from jaeger_os.contract.modules import ModuleSpec

# The two directories module.yaml files live under. Derived the same
# way (relative to this file, not cwd) so discovery works regardless
# of where the process was launched from.
NODES_DIR = pathlib.Path(__file__).resolve().parents[1] / "nodes"
PLUGINS_DIR = pathlib.Path(__file__).resolve().parents[1] / "plugins"


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
) -> dict[str, list[ModuleSpec]]:
    """Scan one or more roots' immediate subdirectories for
    ``module.yaml`` and return every module found across ALL roots,
    keyed by slot. Default roots: ``(NODES_DIR, PLUGINS_DIR)`` — the
    two directories that hold module.yaml files in this repo.

    A single ``pathlib.Path`` is also accepted (normalized to a
    one-tuple) for callers/tests that only care about one directory.

    Directories without a ``module.yaml`` are skipped silently (not
    every node/plugin package is a module yet). A directory *with* a
    ``module.yaml`` that fails validation raises — a broken module
    must fail loudly, not disappear from discovery. A slot can span
    multiple modules across roots (e.g. ``messaging`` — discord,
    telegram, imessage all live under ``plugins/`` and share the
    slot); callers doing ANY-OF readiness must consult every entry."""
    if roots is None:
        roots = (NODES_DIR, PLUGINS_DIR)
    elif isinstance(roots, (str, pathlib.Path)):
        roots = (pathlib.Path(roots),)
    by_slot: dict[str, list[ModuleSpec]] = {}
    for root in roots:
        root = pathlib.Path(root)
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if not (child / "module.yaml").is_file():
                continue
            spec = load_module(child)
            by_slot.setdefault(spec.slot, []).append(spec)
    return by_slot


__all__ = [
    "ModuleSpec", "load_module", "discover_modules", "module_platform_ok",
    "NODES_DIR", "PLUGINS_DIR",
]
