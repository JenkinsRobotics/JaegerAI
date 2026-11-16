"""One profile: Jaeger. Replaces the Hermes multi-profile layer."""
from __future__ import annotations
from pathlib import Path


def get_active_profile_name() -> str:
    return "jaeger"


def get_active_hermes_home() -> Path:
    from jaeger_ai.core.instance.instance import resolve_instance_dir
    return Path(resolve_instance_dir())


def _profiles_match(a, b) -> bool:
    return str(a or "jaeger") == str(b or "jaeger")
