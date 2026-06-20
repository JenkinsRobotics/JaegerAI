"""``jaeger runtime`` — inspect + select inference engines (JROS's
equivalent of LM Studio's Settings → Runtime panel).

Each model FORMAT (GGUF / MLX) maps to a chosen ENGINE. ``"auto"`` lets
the registry pick the best installed engine for the format.

  jaeger runtime                     show the panel: per-format selection
                                     + every engine, version, install state
  jaeger runtime use gguf llama-cpp-python
  jaeger runtime use mlx  mlx-vlm    pick the MLX engine
  jaeger runtime use mlx  auto       reset a format to auto
  jaeger runtime -i work             a specific instance
"""

from __future__ import annotations

from typing import Any

from . import _common as c

_FORMATS = ("gguf", "mlx")


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "runtime",
        help="inspect + select inference engines (the Runtime panel)",
    )
    parser.add_argument(
        "action", nargs="?", default="show", choices=["show", "use"],
        help="'show' the panel (default) or 'use' to set an engine",
    )
    parser.add_argument(
        "format", nargs="?", default=None, choices=list(_FORMATS),
        help="model format to set the engine for (with 'use')",
    )
    parser.add_argument(
        "engine", nargs="?", default=None,
        help="engine id, or 'auto' (with 'use')",
    )
    parser.add_argument(
        "--instance", "-i", default=None,
        help="instance name (default: the active instance)",
    )
    parser.set_defaults(_handler=run_runtime)


def _resolve_layout(args: Any) -> Any:
    if args.instance:
        from jaeger_os.core.instance.instance import (
            InstanceLayout,
            resolve_instance_dir,
        )
        return InstanceLayout(resolve_instance_dir(args.instance))
    return c.get_active_instance_layout()


def _engine_line(spec: Any, *, selected_ids: set[str]) -> str:
    from jaeger_os.core.models.engine_registry import EngineSpec  # noqa: F401
    version = spec.version() or "—"
    if spec.available():
        state = c.green("installed")
    else:
        state = c.yellow(f"install: {spec.install_hint}")
    mark = c.cyan("●") if spec.id in selected_ids else c.grey("○")
    fmts = "/".join(spec.formats)
    return (f"  {mark} {c.bold(spec.display_name):<32} "
            f"{c.grey('[' + spec.id + ']'):<22} "
            f"{fmts:<5} v{version:<10} {state}\n"
            f"      {c.grey(spec.description)}")


def _show(layout: Any) -> int:
    from jaeger_os.core.instance.schemas import Config, load_yaml
    from jaeger_os.core.models import engine_registry as er

    try:
        cfg = load_yaml(layout.config_path, Config)
    except Exception as exc:  # noqa: BLE001
        print(c.red(f"Could not load config: {exc}"))
        return 1

    rt = cfg.runtime
    print(c.bold("\nRuntime — inference engine selection\n"))

    # Per-format selection (the two dropdowns), showing what "auto"
    # currently resolves to for this instance's model.
    print(c.bold("  Runtime selections"))
    model_path = cfg.model.model_path
    for fmt in _FORMATS:
        sel = er.runtime_selection(rt, fmt)
        # What it resolves to for THIS model when the format matches.
        resolved = ""
        if er.detect_format(model_path) == fmt:
            eng = er.resolve_engine(model_path, rt)
            resolved = c.grey(f"  → loads this instance via {eng.display_name}")
        shown = sel if sel != "auto" else c.grey("auto")
        print(f"    {fmt.upper():<5} → {c.cyan(shown)}{resolved}")
    print()

    # The engines & frameworks list (LM Studio's lower panel).
    selected_ids = {
        er.resolve_engine_id_for_selection(rt, fmt) for fmt in _FORMATS
    }
    print(c.bold("  Engines"))
    for spec in er.all_engines():
        print(_engine_line(spec, selected_ids=selected_ids))
    print()
    print(c.grey("  set one with:  jaeger runtime use <gguf|mlx> <engine|auto>"))
    return 0


def _use(layout: Any, fmt: str, engine: str) -> int:
    from jaeger_os.core.instance.schemas import Config, dump_yaml, load_yaml
    from jaeger_os.core.models import engine_registry as er

    try:
        cfg = load_yaml(layout.config_path, Config)
    except Exception as exc:  # noqa: BLE001
        print(c.red(f"Could not load config: {exc}"))
        return 1

    try:
        engine = er.set_runtime_engine(cfg.runtime, fmt, engine)
    except ValueError as exc:
        print(c.red(str(exc)))
        return 2
    dump_yaml(layout.config_path, cfg)

    spec = er.get_engine(engine) if engine != "auto" else None
    warn = ""
    if spec is not None and not spec.available():
        warn = c.yellow(f"  ⚠ {spec.display_name} is not installed yet — "
                        f"{spec.install_hint}")
    print(c.green(f"✓ {fmt.upper()} engine → {engine}") +
          (f"\n{warn}" if warn else ""))
    return 0


def run_runtime(args: Any) -> int:
    layout = _resolve_layout(args)
    if layout is None:
        print(c.red("No active instance. Run `jaeger` to create one first."))
        return 1
    if args.action == "use":
        if not args.format or not args.engine:
            print(c.red("Usage: jaeger runtime use <gguf|mlx> <engine|auto>"))
            return 2
        return _use(layout, args.format, args.engine)
    return _show(layout)
