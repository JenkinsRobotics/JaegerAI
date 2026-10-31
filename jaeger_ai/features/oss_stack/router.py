"""Hub model router: small text -> rack PC Ollama, vision/12B+/embeddings -> Mac.

Mac Ollama is loopback only; the rack PC is reached over Tailscale only.
``*:cloud`` / ``*-cloud`` models go off-box and are never routed.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

MAC_URL = os.environ.get("JAEGER_MAC_OLLAMA", "http://127.0.0.1:11434")
PC_URL = os.environ.get("JAEGER_RACKPC_OLLAMA", "http://100.78.245.49:11434")
PC_MODEL = os.environ.get("JAEGER_RACKPC_MODEL", "qwen3:8b")
MAC_SMALL = os.environ.get("JAEGER_MAC_SMALL_MODEL", "qwen3:4b")
MAC_VISION = os.environ.get("JAEGER_MAC_VISION_MODEL", "qwen3-vl:8b")
MAC_LARGE = os.environ.get("JAEGER_MAC_LARGE_MODEL", "gemma4:12b")
EMBED_MODEL = os.environ.get("JAEGER_EMBED_MODEL", "qwen3-embedding:0.6b")
SMALL_MAX_B = 8.0
LARGE_MIN_B = 12.0
VISION_HINTS = ("-vl", "vl:", "vision", "minicpm-v", "llava")
EMBED_HINTS = ("embed",)
HEALTH_TTL = 30.0
GEN_TIMEOUT = float(os.environ.get("JAEGER_ROUTER_TIMEOUT_S", "300"))


class RouteError(Exception):
    def __init__(self, message: str, status: int = 400, extra: dict | None = None):
        super().__init__(message)
        self.status = status
        self.extra = extra or {}


def is_cloud(model: str) -> bool:
    m = (model or "").lower()
    return m.endswith(":cloud") or m.endswith("-cloud") or ":cloud" in m or "-cloud" in m.split(":")[-1]


def size_b(model: str) -> float | None:
    hits = re.findall(r"(\d+(?:\.\d+)?)b\b", (model or "").lower())
    return float(hits[-1]) if hits else None


def kind_of(model: str) -> str:
    m = (model or "").lower()
    if any(h in m for h in EMBED_HINTS):
        return "embed"
    if any(h in m for h in VISION_HINTS):
        return "vision"
    return "text"


def _get_json(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - fixed hosts
        return json.loads(r.read() or b"{}")


def _post_json(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed hosts
        return json.loads(r.read() or b"{}")


class Health:
    def __init__(self, fetch=_get_json, clock=time.monotonic):
        self.fetch, self.clock, self._cache = fetch, clock, {}

    def mark_down(self, base: str) -> None:
        self._cache[base] = (self.clock(), None)

    def models(self, base: str) -> set[str] | None:
        """Local model names at ``base`` (cloud excluded) or None when down."""
        hit = self._cache.get(base)
        if hit and self.clock() - hit[0] < HEALTH_TTL:
            return hit[1]
        try:
            tags = self.fetch(base + "/api/tags", 2.5)
            names = {m.get("name", "") for m in tags.get("models", [])
                     if not m.get("remote_host") and not is_cloud(m.get("name", ""))}
        except (OSError, ValueError, urllib.error.URLError):
            names = None
        self._cache[base] = (self.clock(), names)
        return names


def decide(req: dict, health: Health, mac_gate=None) -> dict:
    """Pick target/model. ``mac_gate(kind, model)`` returns busy reasons ([] = go)."""
    model = (req.get("model") or "").strip()
    kind = req.get("kind") or ("vision" if req.get("images") else (kind_of(model) if model else "text"))
    if kind not in {"text", "vision", "embed"}:
        raise RouteError("kind must be text, vision or embed")
    if model and is_cloud(model):
        raise RouteError("Cloud models are excluded from Jaeger routing (they leave the Mac)", 400)
    size = size_b(model) if model else None
    large = bool(req.get("large")) or (size is not None and size >= LARGE_MIN_B)
    reason, target = "", "mac"
    if kind == "embed":
        model, reason = model or EMBED_MODEL, "embeddings stay on the Mac"
    elif kind == "vision":
        model, reason = model or MAC_VISION, "vision runs on the Mac"
    elif large:
        model, reason = model or MAC_LARGE, "12B+ runs on the Mac"
    else:
        want = model or PC_MODEL
        pc = health.models(PC_URL)
        small = size_b(want) is None or size_b(want) <= SMALL_MAX_B
        if pc is not None and small and want in pc:
            target, model, reason = "rackpc", want, "small text -> rack PC GPU"
        else:
            reason = ("rack PC down, fallback to Mac" if pc is None
                      else f"{want} not on rack PC, using Mac")
            mac = health.models(MAC_URL) or set()
            model = want if want in mac else MAC_SMALL
    out = {"target": target, "model": model, "kind": kind, "large": large, "reason": reason,
           "base": PC_URL if target == "rackpc" else MAC_URL}
    if target == "mac" and mac_gate is not None:
        busy = mac_gate("heavy" if large else "light", model) or []
        if busy:
            raise RouteError("Mac is busy; try again shortly", 503, {"busy": busy, "decision": out})
    return out


def unload_others(model: str, fetch=_get_json, post=_post_json) -> list[str]:
    """One large model on the Mac at a time: unload other loaded models first."""
    dropped = []
    try:
        for m in fetch(MAC_URL + "/api/ps", 3).get("models", []):
            name = m.get("name") or m.get("model")
            if name and name != model:
                post(MAC_URL + "/api/generate", {"model": name, "keep_alive": 0}, 10)
                dropped.append(name)
    except (OSError, ValueError, urllib.error.URLError):
        pass
    return dropped


def run(decision: dict, req: dict, post=_post_json) -> dict:
    base, model = decision["base"], decision["model"]
    t0 = time.monotonic()
    if decision["kind"] == "embed":
        data = post(base + "/api/embed", {"model": model, "input": req.get("input") or req.get("prompt") or ""}, GEN_TIMEOUT)
        return {"embeddings": data.get("embeddings", []), "elapsed_s": round(time.monotonic() - t0, 2)}
    messages = req.get("messages") or [{"role": "user", "content": str(req.get("prompt") or "")}]
    if req.get("images"):
        messages[-1] = {**messages[-1], "images": req["images"]}
    body = {"model": model, "messages": messages, "stream": False,
            "options": {"num_predict": int(req.get("max_tokens") or 1024)}}
    if req.get("think") is not None:
        body["think"] = bool(req["think"])
    data = post(base + "/api/chat", body, GEN_TIMEOUT)
    return {"text": (data.get("message") or {}).get("content", ""),
            "elapsed_s": round(time.monotonic() - t0, 2), "eval_count": data.get("eval_count")}


def mac_gate_default(state_root: Path | None = None):
    root = state_root or Path(os.environ.get("JAEGER_STATE_DIR", Path.home() / ".jaeger"))

    def gate(kind, model):
        try:
            from jaeger_ai.features.webui.api.resource_manager import ResourceManager
            return ResourceManager(lambda: root).check(kind, model)
        except Exception:  # noqa: BLE001 - broken probe must not block forever
            return []
    return gate
