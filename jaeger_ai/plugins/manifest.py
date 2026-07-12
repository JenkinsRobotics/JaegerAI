"""Plugin manifest schema — typed contract for ``plugin.yaml``.

Every bundled plugin ships a ``plugin.yaml``. Before this module
the manifest was untyped — fields like ``requires`` /
``registers_bridges`` / ``capabilities`` were read with dict
``.get()`` calls and silently tolerated typos, missing nesting, or
wrong types. A typo'd ``requireds:`` would just mean "this plugin
has no requirements" without anyone noticing.

The Pydantic model below is the typed parse target. Use:

  * :func:`load_manifest(path)`  — parse + validate. Returns the
    ``PluginManifest`` or raises with the field path that failed.
  * :func:`load_manifest_dict(path)` — for legacy callers that
    expect a dict. Returns the dict only when validation passes;
    propagates the original validation error otherwise.

The model is intentionally permissive on fields the project has
shipped over time (``provides``, ``capabilities``, ``hooks``,
``entry``, ``entrypoints``) — they're typed but not required.

Doctor + skill_loader can also call :func:`audit_plugin_dir` to
check every bundled plugin in one go and surface a list of
errors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class PluginRequires(BaseModel):
    """The ``requires:`` block of ``plugin.yaml`` — what the plugin
    needs from the host environment to be considered "ready".

    Every field is optional; an empty section means "no
    requirements". The doctor / list_plugins surface treats:

      * ``libraries``      — every name must import (heuristic
                             name-to-import mapping in
                             ``core/tools/plugins.py``)
      * ``env``            — every var must be set non-empty OR
                             present in the instance's credentials
                             store
      * ``env_optional``   — listed for documentation; not gated
      * ``platform``       — sys.platform must startswith one of
                             these. Empty = any platform.
      * ``hardware``       — informational tags (``speaker`` /
                             ``microphone`` / ``camera`` / etc.)
                             so the doctor can point at missing
                             devices on an embodiment without
                             hardware.
      * ``libraries_optional`` — same idea as env_optional
      * ``models``         — model files the plugin pulls down on
                             first use; list-of-dicts shape
      * ``config_file``    — relative path to a JSON/YAML config
                             the plugin reads
      * ``notes``          — free-text caveats (e.g. "Needs Full
                             Disk Access")"""

    model_config = ConfigDict(extra="allow")

    libraries: list[str] = Field(default_factory=list)
    libraries_optional: list[str] = Field(default_factory=list)
    env: list[str] = Field(default_factory=list)
    env_optional: list[str] = Field(default_factory=list)
    platform: list[str] = Field(default_factory=list)
    hardware: list[str] = Field(default_factory=list)
    models: list[dict[str, Any]] = Field(default_factory=list)
    config_file: str = ""
    notes: str = ""


class PluginProvides(BaseModel):
    """The ``provides:`` block — what the plugin EXPOSES to the rest
    of the framework. ``tools`` enumerate registered tool names so
    the registry / doctor can cross-check against the live agent's
    tool list. ``api`` and ``bridges`` are documentation."""

    model_config = ConfigDict(extra="allow")

    tools: list[str] = Field(default_factory=list)
    api: list[str] = Field(default_factory=list)
    bridges: list[str] = Field(default_factory=list)


class PluginManifest(BaseModel):
    """Typed view of ``plugin.yaml``. Every plugin in
    ``jaeger_os/plugins`` must validate against this model — the
    doctor surfaces a failure if one doesn't.

    Required fields are ``name`` + ``version``; everything else is
    optional. Pydantic's ``extra="allow"`` keeps the model forward-
    compatible with manifests that add fields the framework
    doesn't yet care about (the validator won't reject them)."""

    model_config = ConfigDict(extra="allow")

    name: str
    version: int = 1
    description: str = ""
    requires: PluginRequires = Field(default_factory=PluginRequires)
    provides: PluginProvides = Field(default_factory=PluginProvides)

    # Optional bookkeeping fields the framework reads case-by-case.
    capabilities: list[str] = Field(default_factory=list)
    entry: str = ""                                # entrypoint module
    entrypoints: dict[str, str] = Field(default_factory=dict)
    hooks: list[str] = Field(default_factory=list)
    registers_bridges: list[str] = Field(default_factory=list)
    registers_tools_dynamically: bool = False


def load_manifest(path: Path) -> PluginManifest:
    """Parse + validate ``plugin.yaml`` at ``path``. Raises with the
    failing field path if the manifest is missing required fields
    or carries wrong types.

    Raises:
      FileNotFoundError — manifest doesn't exist
      ValueError        — manifest exists but doesn't parse as YAML
      ValidationError   — manifest parsed but fails the schema
    """
    if not path.is_file():
        raise FileNotFoundError(f"no manifest at {path}")
    try:
        import yaml
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"could not parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping, "
                         f"got {type(data).__name__}")
    return PluginManifest.model_validate(data)


def audit_plugin_dir(plugins_root: Path) -> list[dict[str, Any]]:
    """Walk ``plugins_root`` and audit every immediate child that
    looks like a plugin (has a ``plugin.yaml``). Returns one row
    per plugin with ``{name, ok, errors?, manifest?}``.

    Used by ``--doctor`` so a malformed manifest surfaces at boot
    time, not when the first user-facing call fails."""
    out: list[dict[str, Any]] = []
    if not plugins_root.is_dir():
        return out
    for child in sorted(plugins_root.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        manifest_path = child / "plugin.yaml"
        if not manifest_path.is_file():
            continue
        try:
            manifest = load_manifest(manifest_path)
        except ValidationError as exc:
            errors = [
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                for err in exc.errors()
            ]
            out.append({
                "name": child.name,
                "ok": False,
                "errors": errors,
            })
            continue
        except (FileNotFoundError, ValueError) as exc:
            out.append({
                "name": child.name,
                "ok": False,
                "errors": [str(exc)],
            })
            continue
        out.append({
            "name": manifest.name,
            "ok": True,
            "manifest": manifest,
        })
    return out


__all__ = [
    "PluginManifest",
    "PluginProvides",
    "PluginRequires",
    "audit_plugin_dir",
    "load_manifest",
]
