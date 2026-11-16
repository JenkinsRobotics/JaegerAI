"""Public Ollama Cloud inventory; no credentials, inference, or model pulls."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import threading
import time
import urllib.request

_lock = threading.Lock()
_cache = None
_expires = 0.0


def _request(path, body=None):
    request = urllib.request.Request(
        "https://ollama.com/api/" + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=4) as response:
        return json.load(response)


def cloud_tag(name):
    return name + ("-cloud" if ":" in name else ":cloud")


def context_limit(info):
    architecture = info.get("general.architecture")
    value = info.get(f"{architecture}.context_length")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _model(row):
    name = row["name"]
    result = {"name": name, "local_name": cloud_tag(name),
              "capabilities": row.get("capabilities") or [], "context_length": None}
    try:
        details = _request("show", {"model": name})
        result["context_length"] = context_limit(details.get("model_info") or {})
        result["capabilities"] = details.get("capabilities") or result["capabilities"]
    except (OSError, ValueError):
        # A metadata failure must not hide a model or invent its limit.
        pass
    return result


def catalog(refresh=False):
    global _cache, _expires
    with _lock:
        if _cache is not None and not refresh and time.monotonic() < _expires:
            return deepcopy(_cache)
        try:
            payload = _request("tags")
            rows = payload["models"]
            if not isinstance(rows, list):
                raise ValueError("Invalid Ollama Cloud catalog")
            unique = {r["name"]: r for r in rows if isinstance(r, dict) and isinstance(r.get("name"), str) and r["name"]}
            with ThreadPoolExecutor(max_workers=8) as pool:
                models = list(pool.map(_model, unique.values()))
            _cache = {"models": models, "stale": False, "updated_at": time.time()}
            _expires = time.monotonic() + 300
            return deepcopy(_cache)
        except (OSError, ValueError, KeyError, TypeError):
            return {**deepcopy(_cache or {"models": [], "updated_at": None}),
                    "stale": True, "error": "Ollama Cloud catalog unavailable; displayed entries may be outdated."}
