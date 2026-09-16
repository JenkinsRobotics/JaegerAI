"""Jaeger-owned, host-specific Ollama discovery and routing for Hermes WebUI.

Copied into api/ by the Jaeger WebUI overlay. No credentials or host addresses
live here: each profile supplies the same ollama_hosts configuration.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
import urllib.request

_cache = {}
_lock = threading.Lock()


def hosts(config):
    entries = config.get("ollama_hosts", {})
    return entries if isinstance(entries, dict) else {}


def resolve(model, config):
    """Preserve the complete tag and never substitute a different host."""
    entries = hosts(config)
    if not entries:
        return None
    value = str(model or config.get("model", {}).get("default", ""))
    if value.startswith("@ollama-"):
        lane, separator, name = value[1:].partition(":")
        key = lane.removeprefix("ollama-")
        if not separator or not name or key not in entries:
            raise ValueError("Unknown Ollama host or empty model selection")
        return name, "ollama", entries[key]["base_url"].rstrip("/")
    # Repair legacy selections made when the UI exposed Ollama as Custom.
    if value.startswith("@custom:") and value.count(":") == 2:
        value = value.removeprefix("@custom:")
    if not value.startswith("@"):
        model_cfg = config.get("model", {})
        if model_cfg.get("provider") == "ollama":
            return value, "ollama", model_cfg.get("base_url")
    return None


def _probe(key, entry, refresh=False, cached_only=False):
    base = entry["base_url"].rstrip("/")
    label = entry.get("label", key)
    cache_key = (key, base, label)
    with _lock:
        cached = _cache.get(cache_key)
    if cached and (cached_only or (not refresh and time.monotonic() - cached[0] < 30)):
        return cached[1]
    group = {"provider": f"Ollama · {label}", "provider_id": f"ollama-{key}",
             "models": [], "host": key, "base_url": base, "status": "unknown"}
    if cached_only:
        return group
    native = base.removesuffix("/v1")
    try:
        with urllib.request.urlopen(native + "/api/tags", timeout=3) as response:
            rows = json.load(response).get("models", [])
        for row in rows:
            name = row.get("name") or row.get("model")
            caps = row.get("capabilities", [])
            if not name or (caps and "completion" not in caps) or "embed" in name.lower():
                continue
            cloud = bool(row.get("remote_host")) or name.endswith(":cloud") or name.endswith("-cloud")
            group["models"].append({"id": f"@ollama-{key}:{name}",
                                    "label": f"{name} ({'Cloud' if cloud else 'Local'})"})
        group["status"] = "online"
    except Exception as exc:
        group["status"] = "unavailable"
        group["error"] = type(exc).__name__
        group["provider"] += " — unavailable"
    with _lock:
        _cache[cache_key] = (time.monotonic(), group)
    return group


def catalog(config, *, refresh=False, cached_only=False):
    entries = hosts(config)
    if not entries:
        return None
    with ThreadPoolExecutor(max_workers=min(8, len(entries))) as pool:
        groups = list(pool.map(lambda item: _probe(*item, refresh, cached_only), entries.items()))
    model_cfg = config.get("model", {})
    base = str(model_cfg.get("base_url", "")).rstrip("/")
    active = next((f"ollama-{key}" for key, entry in entries.items()
                   if entry["base_url"].rstrip("/") == base), "ollama")
    default = model_cfg.get("default", "")
    return {"active_provider": active, "default_model": f"@{active}:{default}", "groups": groups}
