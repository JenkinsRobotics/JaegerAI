"""Expose hermes-agent's COMMAND_REGISTRY to the webui frontend.

This module is the single integration point with hermes_cli.commands.
If hermes-agent is unavailable the endpoint degrades to an empty list
so the frontend can still load with WEBUI_ONLY commands.
"""
from __future__ import annotations
from contextlib import nullcontext
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)





























def _load_config_for_moa_resolution() -> dict:
    from hermes_cli.config import load_config

    cfg = load_config()
    return cfg if isinstance(cfg, dict) else {}


def resolve_moa_config(preset: str | None = None) -> dict:
    try:
        from hermes_cli.moa_config import moa_usage, normalize_moa_config
    except ImportError as exc:
        raise RuntimeError("MoA runtime unavailable (hermes-agent not installed or too old)") from exc
    try:
        from hermes_cli.moa_config import resolve_moa_preset
    except ImportError:
        resolve_moa_preset = None

    try:
        cfg = _load_config_for_moa_resolution()
        moa_raw = cfg.get("moa") if isinstance(cfg, dict) else {}
        moa_cfg = normalize_moa_config(moa_raw)
    except Exception:
        moa_raw = {}
        moa_cfg = normalize_moa_config({})

    preset_name = str(preset or moa_cfg.get("default_preset") or "default").strip()
    if preset_name not in (moa_cfg.get("presets") or {}):
        preset_name = str(moa_cfg.get("default_preset") or "default")

    selected = {}
    if resolve_moa_preset is not None:
        try:
            selected = resolve_moa_preset(moa_raw, preset_name)
            if not isinstance(selected, dict):
                selected = {}
        except Exception:
            selected = {}
            preset_name = str(moa_cfg.get("default_preset") or "default")

    resolved = dict(moa_cfg)
    resolved.update(selected)
    resolved["preset"] = preset_name
    resolved["usage"] = moa_usage()
    return resolved


