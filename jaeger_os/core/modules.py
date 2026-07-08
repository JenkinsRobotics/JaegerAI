"""module.yaml → validated ``ModuleSpec`` (the engine-module discovery seam).

A module directory (``jaeger_os/nodes/<name>/``) holds ``module.yaml``
declaring its slot, topics, tools, and factory. The loader validates
STRICTLY (unknown fields refuse, missing factory refuses, empty slot
refuses) — loudly at load time with the offending file named, never a
silent degrade. Mirrors ``jaeger_os/hardware/package.py``'s house style.

``discover_modules`` walks the immediate subdirectories of a root
(default ``jaeger_os/nodes``) and returns every module keyed by slot.
A broken ``module.yaml`` raises rather than being skipped — a typo in
a shipped module must fail loudly, not vanish from discovery.

NO manifest.py changes here: manifests keep explicit factory strings
for now. module.yaml is authoritative *metadata*; slot-resolution
binding (manifests picking a factory *by slot*) is a later step.
"""

from __future__ import annotations

import pathlib

import msgspec


class ModuleSpec(msgspec.Struct, forbid_unknown_fields=True):
    module: str
    slot: str
    factory: str
    version: str = ""
    consumes: list[str] = []
    produces: list[str] = []
    tools: list[str] = []
    config: str = ""


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


def discover_modules(
    root: pathlib.Path | None = None,
) -> dict[str, list[ModuleSpec]]:
    """Scan ``root``'s immediate subdirectories for ``module.yaml`` and
    return every module found, keyed by slot.

    Directories without a ``module.yaml`` are skipped silently (not
    every node package is a module yet). A directory *with* a
    ``module.yaml`` that fails validation raises — a broken module
    must fail loudly, not disappear from discovery."""
    if root is None:
        root = pathlib.Path(__file__).resolve().parents[1] / "nodes"
    root = pathlib.Path(root)
    by_slot: dict[str, list[ModuleSpec]] = {}
    if not root.is_dir():
        return by_slot
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "module.yaml").is_file():
            continue
        spec = load_module(child)
        by_slot.setdefault(spec.slot, []).append(spec)
    return by_slot


__all__ = ["ModuleSpec", "load_module", "discover_modules"]
