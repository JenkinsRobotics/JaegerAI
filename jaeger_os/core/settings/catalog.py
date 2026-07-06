"""The settings catalog — derived from the Pydantic schemas, once.

``catalog``/``groups``/``describe`` walk the ``Config`` model and emit a
JSON-ready descriptor per EXPOSED leaf field (a leaf carrying
``json_schema_extra`` set by :func:`jaeger_os.core.instance.schemas._setting`).
``set_value`` coerces + validates a change back through the same model and
persists it via the schema's own ``dump_yaml``. Every surface — ``jaeger
settings`` and the Swift app — reads and writes through here, so a setting is
defined ONCE (the annotated ``Field``) and rendered everywhere. There is no
hand-enumerated field list in the CLI, the bridge, or the Swift app.

Deliberately a plain module over the ``Config`` model — NOT a plugin / provider
framework. When a future module (a TTS node, a plugin, a hardware package) needs
to contribute its own settings to this surface, that federation seam is a 0.8
concern (``dev/docs/framework_vision.md``); today the whole catalog is the
config schema.
"""

from __future__ import annotations

import types
import typing
from typing import Any

from jaeger_os.core.instance.schemas import Config, dump_yaml, load_yaml

# Page order for grouped output — the eight spec groups, then any spill-over.
GROUP_ORDER = [
    "model", "display", "voice", "tts", "autonomy",
    "permissions", "retention", "interaction", "general",
]


# ---------------------------------------------------------------------------
# type + constraint introspection
# ---------------------------------------------------------------------------
def _unwrap_optional(ann: Any) -> Any:
    """``X | None`` / ``Optional[X]`` → ``X``; other annotations pass through."""
    origin = typing.get_origin(ann)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return ann


def _kind_and_choices(ann: Any) -> tuple[str | None, list[Any] | None]:
    """Map a leaf annotation to (catalog type, choices). Returns
    ``(None, None)`` for types the catalog can't render (Path, list, …) —
    those leaves are simply skipped."""
    ann = _unwrap_optional(ann)
    if typing.get_origin(ann) is typing.Literal:
        return "enum", list(typing.get_args(ann))
    if ann is bool:
        return "bool", None
    if ann is int:
        return "int", None
    if ann is float:
        return "float", None
    if ann is str:
        return "str", None
    return None, None


def _validation(field_info: Any) -> dict[str, Any]:
    """Pull min/max/pattern out of the field's annotated-type metadata."""
    out: dict[str, Any] = {}
    for meta in getattr(field_info, "metadata", []) or []:
        for attr, key in (("ge", "min"), ("gt", "min"),
                          ("le", "max"), ("lt", "max")):
            val = getattr(meta, attr, None)
            if val is not None:
                out[key] = val
        pattern = getattr(meta, "pattern", None)
        if pattern is not None:
            out["pattern"] = pattern
    return out


def _label(path: str) -> str:
    leaf = path.rsplit(".", 1)[-1]
    words = leaf.replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else path


# ---------------------------------------------------------------------------
# schema walk → descriptors
# ---------------------------------------------------------------------------
def _load(layout: Any) -> Config:
    return load_yaml(layout.config_path, Config)


def _descriptors(layout: Any) -> list[dict[str, Any]]:
    """One descriptor per exposed ``Config`` leaf, current values from disk."""
    cfg = _load(layout)
    out: list[dict[str, Any]] = []
    _walk(type(cfg), cfg, "", out)
    return out


def _walk(model_cls: type, instance: Any, prefix: str,
          out: list[dict[str, Any]]) -> None:
    from pydantic import BaseModel
    for name, field_info in model_cls.model_fields.items():
        path = f"{prefix}{name}"
        value = getattr(instance, name, None)
        ann = _unwrap_optional(field_info.annotation)
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            _walk(ann, value, path + ".", out)
            continue
        extra = field_info.json_schema_extra
        if not isinstance(extra, dict) or "group" not in extra:
            continue  # not exposed — identity keys, provenance, deferred blocks
        kind, choices = _kind_and_choices(field_info.annotation)
        if kind is None:
            continue  # unrenderable type (Path, list) — skip, don't fabricate
        default = field_info.get_default(call_default_factory=False)
        desc: dict[str, Any] = {
            "path": path,
            "label": _label(path),
            "group": extra.get("group") or "general",
            "type": kind,
            "default": default,
            "current": value,
            "description": (field_info.description or "").strip(),
            "restart": bool(extra.get("restart", False)),
            "advanced": bool(extra.get("advanced", False)),
            "validation": _validation(field_info),
        }
        if choices is not None:
            desc["choices"] = choices
        out.append(desc)


def _assign(data: dict[str, Any], segments: list[str], value: Any) -> None:
    node = data
    for seg in segments[:-1]:
        node = node[seg]
    node[segments[-1]] = value


def _read_path(model: Any, path: str) -> Any:
    node: Any = model
    for seg in path.split("."):
        node = getattr(node, seg)
    return node


def _fmt_validation_error(path: str, exc: Any) -> str:
    errs = exc.errors()
    if errs:
        msg = errs[0].get("msg", str(exc))
        return f"invalid value for {path}: {msg}"
    return f"invalid value for {path}: {exc}"


# ---------------------------------------------------------------------------
# public API — surfaces call these
# ---------------------------------------------------------------------------
def catalog(layout: Any, *, advanced: bool = True,
            group: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Grouped descriptors: ``{group: [descriptor, ...]}``, groups ordered
    per :data:`GROUP_ORDER`. ``advanced=False`` hides advanced fields;
    ``group`` narrows to a single page."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for desc in _descriptors(layout):
        if not advanced and desc["advanced"]:
            continue
        if group is not None and desc["group"] != group:
            continue
        grouped.setdefault(desc["group"], []).append(desc)
    ordered: dict[str, list[dict[str, Any]]] = {}
    for name in _ordered_groups(grouped.keys()):
        ordered[name] = sorted(grouped[name], key=lambda d: (d["advanced"], d["path"]))
    return ordered


def groups(layout: Any) -> list[dict[str, Any]]:
    """One entry per live group: ``{name, count}`` in page order."""
    counts: dict[str, int] = {}
    for desc in _descriptors(layout):
        counts[desc["group"]] = counts.get(desc["group"], 0) + 1
    return [{"name": n, "count": counts[n]} for n in _ordered_groups(counts.keys())]


def describe(layout: Any, path: str) -> dict[str, Any] | None:
    """The single descriptor for ``path``, or ``None`` if not exposed."""
    for desc in _descriptors(layout):
        if desc["path"] == path:
            return desc
    return None


def get_value(layout: Any, path: str) -> Any:
    """The current value at ``path``. Raises ``KeyError`` if not exposed."""
    if describe(layout, path) is None:
        raise KeyError(f"unknown setting: {path!r}")
    return _read_path(_load(layout), path)


def set_value(layout: Any, path: str, value: Any) -> dict[str, Any]:
    """Validate + persist a change, round-tripping through the ``Config``
    model (coerce + validate + ``dump_yaml``). Returns ``{ok, restart_required,
    path, value}``. Raises ``ValueError`` on an unknown path or invalid value."""
    from pydantic import ValidationError
    desc = describe(layout, path)
    if desc is None:
        raise ValueError(f"unknown setting: {path!r}")
    cfg = _load(layout)
    data = cfg.model_dump()
    _assign(data, path.split("."), value)
    try:
        new = Config.model_validate(data)
    except ValidationError as exc:
        raise ValueError(_fmt_validation_error(path, exc)) from exc
    dump_yaml(layout.config_path, new)
    return {"ok": True, "restart_required": desc["restart"],
            "path": path, "value": _read_path(new, path)}


def _ordered_groups(names: Any) -> list[str]:
    present = set(names)
    ordered = [g for g in GROUP_ORDER if g in present]
    ordered += sorted(present - set(GROUP_ORDER))
    return ordered
