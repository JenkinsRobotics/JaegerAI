"""``jaeger config`` — see every setting, its value, default, and what it does.

Walks the instance's ``config.yaml`` against the typed schema
(``core/instance/schemas.py`` — the single source of truth for settings and
their defaults) and prints each field's effective value, the schema default,
whether it's overridden, and the field's description.

  jaeger config              all settings for the active instance
  jaeger config -i work      a specific instance
  jaeger config --changed    only settings overridden from their default
"""

from __future__ import annotations

import textwrap
from typing import Any

from . import _common as c


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "config",
        help="view effective settings + defaults + descriptions",
    )
    parser.add_argument(
        "--instance", "-i", default=None,
        help="instance name (default: the active instance)",
    )
    parser.add_argument(
        "--changed", action="store_true",
        help="show only settings overridden from their default",
    )
    parser.set_defaults(_handler=run_config)


def _resolve_layout(args: Any) -> Any:
    if args.instance:
        from jaeger_os.core.instance.instance import (
            InstanceLayout,
            resolve_instance_dir,
        )
        return InstanceLayout(resolve_instance_dir(args.instance))
    return c.get_active_instance_layout()


def _fmt(value: Any) -> str:
    if isinstance(value, str):
        return repr(value) if (value == "" or " " in value) else value
    if isinstance(value, list) and not value:
        return "[]"
    return str(value)


def run_config(args: Any) -> int:
    layout = _resolve_layout(args)
    if layout is None:
        print(c.red("  no active instance — run `jaeger instances create` first"))
        return 1

    from jaeger_os.core.instance.schemas import Config, load_yaml
    try:
        cfg = load_yaml(layout.config_path, Config)
    except Exception as exc:  # noqa: BLE001
        print(c.red(f"  config unreadable: {exc}"))
        return 1

    from pydantic import BaseModel
    try:
        from pydantic_core import PydanticUndefined
    except Exception:  # noqa: BLE001
        PydanticUndefined = object()  # type: ignore[assignment]

    print()
    print(f"  {c.bold('Settings')}  ·  instance {c.cyan(layout.root.name)}")
    print(c.dim(f"  schema: core/instance/schemas.py   ·   values: {layout.config_path}"))
    print(c.dim("  ✱ marks a setting overridden from its schema default"))
    print()

    def walk(model: BaseModel, prefix: str) -> None:
        for name, info in type(model).model_fields.items():
            value = getattr(model, name)
            path = f"{prefix}{name}"
            if isinstance(value, BaseModel):
                if not args.changed:
                    print(f"  {c.bold(path)}")
                walk(value, path + ".")
                continue
            default = info.default
            has_default = default is not PydanticUndefined
            overridden = has_default and value != default
            if args.changed and not overridden:
                continue
            star = c.cyan("✱") if overridden else " "
            dflt = c.dim(f"(default {_fmt(default)})") if has_default and overridden else ""
            print(f"    {star} {path:<26} = {c.bold(_fmt(value))}  {dflt}")
            if info.description:
                for line in textwrap.wrap(info.description, width=72):
                    print(c.dim(f"        {line}"))

    walk(cfg, "")
    print()
    return 0
