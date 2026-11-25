"""``ToolDef`` — canonical single-source-of-truth tool contract (standalone jaeger-tools)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel

from .arg_coercion import coerce_args


def tool_result_failed(result: Any) -> bool:
    """Recognize native and MCP failure envelopes before result truncation."""
    return isinstance(result, dict) and (
        result.get("ok") is False
        or result.get("success") is False
        or result.get("isError") is True
        or bool(result.get("error"))
    )


def dev_mode_enabled() -> bool:
    """Whether this process runs in dev mode (``JAEGER_DEV_MODE``)."""
    return (os.environ.get("JAEGER_DEV_MODE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


@dataclass
class ToolDef:
    """One callable tool, plus metadata and wire-format renderers."""

    name: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[..., Any]
    interactive: bool = False
    dangerous: bool = False
    beta: bool = False
    toolset: str = ""
    permission_tier: str = ""
    side_effect: str = ""
    max_result_chars: int = 0
    check_fn: Callable[[], bool] | None = None
    requires_env: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()

    def is_available(self) -> bool:
        if self.check_fn is not None:
            try:
                return bool(self.check_fn())
            except Exception:  # noqa: BLE001
                return False
        if self.requires_env:
            return all(os.environ.get(k) for k in self.requires_env)
        return True

    def to_anthropic_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.args_model.model_json_schema(),
        }

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }

    def to_hermes_xml_block(self) -> str:
        return json.dumps(
            {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": self.args_model.model_json_schema(),
                },
            },
            ensure_ascii=True,
        )

    def dispatch(self, raw_args: dict[str, Any]) -> Any:
        coerced = coerce_args(raw_args, self.args_model.model_json_schema())
        validated = self.args_model.model_validate(coerced)
        return self.fn(**validated.model_dump())


__all__ = ["ToolDef", "dev_mode_enabled", "tool_result_failed"]
