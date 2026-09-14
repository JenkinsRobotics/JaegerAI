"""Core instance contract — declared here, filled by the host.

The module read its own instance through the application's pydantic
models: ``jaeger_ai.core.instance.schemas`` for ``Identity`` and
``Config``, ``...instance.instance`` for ``InstanceLayout``. Sixteen
imports, and the wrong direction — a `slot: mind` module cannot require
one particular application's file format to know its own name.

So this states the SMALL contract the agent actually depends on, and
nothing more:

  * :class:`Layout` — a handful of directories and two file paths.
    Structural, so JaegerAI's much richer ``InstanceLayout`` satisfies it
    without inheriting anything or knowing this exists. ``workspace.bind()``
    already injected the object; this makes the TYPE the module's too.
  * :func:`identity_name` — the agent's own name, the one prompt fragment
    the persona pipeline deliberately keeps (see docs/ARCHITECTURE.md §6).
  * :func:`config_section` — the three settings the agent reads out of an
    instance config, with the same defaults the app's models applied.

Plain YAML rather than a validating model, on purpose. The agent is a
CONSUMER of these files, not their owner: the application writes and
validates them, and a second schema here would be a second source of
truth that drifts. Every reader below is best-effort and falls back the
way the call sites already did.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Layout(Protocol):
    """The instance directories the agent touches.

    Structural typing on purpose: any object with these attributes works,
    which is how the host keeps ownership of the real layout while the
    module states only its own needs.
    """

    root: Path
    memory_dir: Path
    logs_dir: Path
    skills_dir: Path
    identity_path: Path
    config_path: Path


def read_yaml(path: Any) -> dict[str, Any]:
    """Parse a YAML mapping, or ``{}`` for anything that goes wrong.

    Missing file, unreadable file, malformed YAML, or a document that is
    not a mapping all mean the same thing to every caller here: no
    configuration, use the defaults.
    """
    try:
        import yaml

        with open(path, encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
    except Exception:  # noqa: BLE001 — an unreadable config is "no config"
        return {}
    return loaded if isinstance(loaded, dict) else {}


def identity_name(layout: Any) -> str:
    """The agent's display name from ``identity.yaml``, or ``""``.

    Empty is a meaningful answer: the ``identity_name`` prompt fragment
    omits itself entirely rather than telling the model it is called
    nothing.
    """
    if layout is None:
        return ""
    return str(read_yaml(getattr(layout, "identity_path", "")).get("name") or "").strip()


def config_section(layout: Any, section: str) -> dict[str, Any]:
    """One top-level section of ``config.yaml`` as a plain dict."""
    if layout is None:
        return {}
    value = read_yaml(getattr(layout, "config_path", "")).get(section)
    return value if isinstance(value, dict) else {}


# ── the three settings the agent reads ─────────────────────────────
# Defaults match what the application's models applied, so behaviour is
# unchanged for an instance that omits them.


def disabled_playbooks(layout: Any) -> set[str]:
    """Skills the operator has switched off. Default: none."""
    raw = config_section(layout, "skills").get("disabled_playbooks") or []
    return {str(name) for name in raw} if isinstance(raw, list) else set()


def include_self_improvement_contract(layout: Any) -> bool:
    """Whether to inject the v2 self-improvement contract. Default: False."""
    return bool(config_section(layout, "skills").get(
        "include_self_improvement_contract", False,
    ))


def plugin_autostart(layout: Any) -> set[str]:
    """Plugins the instance brings live at boot. Default: none."""
    raw = config_section(layout, "plugins").get("autostart") or []
    return {str(n).strip().lower() for n in raw} if isinstance(raw, list) else set()


__all__ = [
    "Layout",
    "config_section",
    "disabled_playbooks",
    "identity_name",
    "include_self_improvement_contract",
    "plugin_autostart",
    "read_yaml",
]
