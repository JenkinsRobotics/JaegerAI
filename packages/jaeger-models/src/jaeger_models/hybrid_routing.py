"""User-owned Hybrid Cloud + Local Model Tier Routing store for jaeger-models.

Lets each user/coworker pick the best model per workload tier in `<state_dir>/model_routing.json`:
- `primary`: flagship chat, coding, and complex reasoning (cloud or local)
- `background`: fast/efficient tier for autonomous self-actions, subagents & cron jobs
- `vision`: local or cloud vision model for Droid camera frames
- `fallback`: local fallback model when cloud is unreachable or offline
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

__all__ = ["HybridRoutingConfig", "HybridRoutingStore"]


@dataclass(frozen=True, slots=True)
class HybridRoutingConfig:
    primary: str = ""
    background: str = ""
    vision: str = "qwen3-vl:8b-instruct"
    fallback: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class HybridRoutingStore:
    """Atomic JSON persistence for `<state_dir>/model_routing.json`."""

    def __init__(self, state_dir: Path) -> None:
        self._path = Path(state_dir).expanduser().resolve() / "model_routing.json"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> HybridRoutingConfig:
        raw: dict[str, Any] = {}
        if self._path.is_file():
            try:
                parsed = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(parsed, Mapping):
                    raw = dict(parsed)
            except (OSError, json.JSONDecodeError):
                raw = {}
        return HybridRoutingConfig(
            primary=str(raw.get("primary") or os.environ.get("JAEGER_MODEL") or "").strip(),
            background=str(raw.get("background") or os.environ.get("JAEGER_BACKGROUND_MODEL") or "").strip(),
            vision=str(raw.get("vision") or os.environ.get("JAEGER_VISION_MODEL") or "qwen3-vl:8b-instruct").strip(),
            fallback=str(raw.get("fallback") or os.environ.get("JAEGER_FALLBACK_MODEL") or "").strip(),
        )

    def update(
        self,
        *,
        primary: str | None = None,
        background: str | None = None,
        vision: str | None = None,
        fallback: str | None = None,
    ) -> HybridRoutingConfig:
        cur = self.load()
        nxt = HybridRoutingConfig(
            primary=cur.primary if primary is None else str(primary).strip(),
            background=cur.background if background is None else str(background).strip(),
            vision=cur.vision if vision is None else (str(vision).strip() or "qwen3-vl:8b-instruct"),
            fallback=cur.fallback if fallback is None else str(fallback).strip(),
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(f".{self._path.name}.tmp.{os.getpid()}")
        tmp.write_text(json.dumps(nxt.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self._path)
        return nxt
