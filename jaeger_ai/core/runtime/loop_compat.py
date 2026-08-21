"""JaegerAI-owned loop glue that used to leak into a sibling jaeger-agent.

The reusable ``jaeger-agent`` package is a pinned dependency, not a working
tree. Product aliases, argument-key cleanup, and cron delivery on
``schedule_prompt`` live here so JaegerAI can run from its own venv pin.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pydantic import create_model

_INSTALLED = False

ARES_TOOL_ALIASES: dict[str, str] = {
    "notes": "mcp__ares-native__notes_operations",
    "apple_notes": "mcp__ares-native__notes_operations",
    "notes_tool": "mcp__ares-native__notes_operations",
    "notes_operations": "mcp__ares-native__notes_operations",
    "todo": "board_view",
    "todowrite": "board_view",
}

_SIBLING_MARKER = "/GitHub/jaeger-agent/"


def _clean_dict_keys(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            str(k).strip().strip('"').strip("'"): _clean_dict_keys(v)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_clean_dict_keys(item) for item in data]
    return data


def sibling_checkout_path() -> Path | None:
    """Return the loaded ``jaeger_agent`` file if it is a sibling checkout."""
    try:
        import jaeger_agent
    except Exception:  # noqa: BLE001
        return None
    file = getattr(jaeger_agent, "__file__", None)
    if not file:
        return None
    path = Path(file).resolve()
    if _SIBLING_MARKER in f"{path.as_posix()}/":
        return path
    return None


def warn_if_sibling_checkout() -> None:
    path = sibling_checkout_path()
    if path is None:
        return
    print(
        "jaeger-agent is loading from a sibling checkout "
        f"({path}). JaegerAI should use the pinned package in its venv.",
        file=sys.stderr,
    )


def _install_tool_aliases() -> None:
    from jaeger_agent.dialects import _shared

    aliases = getattr(_shared, "_TOOL_ALIASES", None)
    if not isinstance(aliases, dict):
        return
    aliases.update(ARES_TOOL_ALIASES)


def _install_arg_key_cleanup() -> None:
    from jaeger_agent.dialects import _shared
    from jaeger_agent.loop import jaeger_agent as loop_mod

    orig_coerce = _shared._coerce_args_dict
    if not getattr(orig_coerce, "_jaeger_ai_clean_keys", False):
        def coerce(parsed: Any) -> dict[str, Any] | None:
            result = orig_coerce(parsed)
            return _clean_dict_keys(result)

        coerce._jaeger_ai_clean_keys = True  # type: ignore[attr-defined]
        _shared._coerce_args_dict = coerce

    orig_prepare = loop_mod.JaegerAgent._prepare_dispatch
    if not getattr(orig_prepare, "_jaeger_ai_clean_keys", False):
        def prepare(self: Any, tc: Any) -> Any:
            raw_args = tc.get("arguments") or {}
            if isinstance(raw_args, dict):
                tc["arguments"] = {
                    str(k).strip().strip('"').strip("'"): v
                    for k, v in raw_args.items()
                }
            return orig_prepare(self, tc)

        prepare._jaeger_ai_clean_keys = True  # type: ignore[attr-defined]
        loop_mod.JaegerAgent._prepare_dispatch = prepare


def _install_schedule_delivery() -> None:
    from jaeger_os.core.tools.tool_registry import get_tool, has_tool

    if not has_tool("schedule_prompt"):
        return
    tool = get_tool("schedule_prompt")
    orig = tool.fn
    if getattr(orig, "_jaeger_ai_deliver_wrap", False):
        return

    def wrapped(
        *args: Any,
        deliver: str | None = None,
        recipient: str | None = None,
        **kwargs: Any,
    ) -> Any:
        result = orig(*args, **kwargs)
        if not deliver or not isinstance(result, dict) or not result.get("scheduled"):
            return result
        try:
            from jaeger_agent.workspace import get_layout

            from jaeger_ai.core.runtime import cron_delivery

            layout = get_layout()
            name = str(result.get("name") or kwargs.get("name") or "")
            result["deliver"] = cron_delivery.remember(
                layout,
                name,
                channel=str(deliver),
                recipient=str(recipient or ""),
            )
        except Exception as exc:  # noqa: BLE001 — schedule still exists
            result["deliver_error"] = str(exc)
        return result

    wrapped._jaeger_ai_deliver_wrap = True  # type: ignore[attr-defined]
    wrapped.__name__ = getattr(orig, "__name__", "schedule_prompt")
    wrapped.__doc__ = orig.__doc__
    tool.fn = wrapped

    fields = getattr(tool.args_model, "model_fields", None) or {}
    if "deliver" not in fields:
        tool.args_model = create_model(
            "SchedulePromptDeliverArgs",
            __base__=tool.args_model,
            deliver=(str | None, None),
            recipient=(str | None, None),
        )


def install() -> None:
    """Idempotent: patch the pinned loop with JaegerAI product glue."""
    global _INSTALLED
    warn_if_sibling_checkout()
    _install_tool_aliases()
    try:
        _install_arg_key_cleanup()
    except Exception:  # noqa: BLE001 — loop import is optional at collect time
        pass
    try:
        _install_schedule_delivery()
    except Exception:  # noqa: BLE001 — tools may not be registered yet
        pass
    _INSTALLED = True


__all__ = [
    "ARES_TOOL_ALIASES",
    "install",
    "sibling_checkout_path",
    "warn_if_sibling_checkout",
]
