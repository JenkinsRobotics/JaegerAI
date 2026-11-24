"""Host-RAM-aware local context window budgeter (Module 01: jaeger-models).

Prevents local inference servers (Ollama, llama.cpp, MLX) from blindly
allocating multi-hundred-thousand-token GGUF training maximums (e.g. 262,144
or 1,048,576) as GPU KV cache on unified-memory laptops, which causes
massive RAM bloat (e.g. 17 GB GPU for a 7.6 GB model) and swap stalls.
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys


@functools.lru_cache(maxsize=1)
def host_total_memory_gb() -> float | None:
    """Return host physical RAM in GiB, or None if unavailable."""
    try:
        if sys.platform == "darwin":
            raw = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], text=True, timeout=2.0
            ).strip()
            return round(int(raw) / (1024**3), 2)
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return round(kb / (1024**2), 2)
    except Exception:
        return None
    return None


def safe_local_context_window(
    reported_ctx: int,
    *,
    host_ram_gb: float | None = None,
    configured_ctx: int = 0,
    env_override: str | None = None,
) -> int:
    """Compute a unified-memory-safe local context ceiling for ``reported_ctx``.

    - Explicit ``configured_ctx`` is always honored (clamped only to ``reported_ctx``).
    - Explicit ``JAEGER_LOCAL_MAX_CTX`` (or ``env_override``) overrides the host tier.
    - Otherwise caps unbounded ``model_info`` training maximums (128K–1M) to a
      host-RAM-safe KV-cache ceiling so local models stay fast and out of swap.
    """
    max_ctx = max(1024, int(reported_ctx or 8192))
    if configured_ctx and int(configured_ctx) > 0:
        return min(int(configured_ctx), max_ctx)

    raw_override = (
        env_override
        if env_override is not None
        else os.environ.get("JAEGER_LOCAL_MAX_CTX", "")
    ).strip()
    if raw_override:
        try:
            ov = int(raw_override)
            if ov >= 1024:
                return min(ov, max_ctx)
        except ValueError:
            pass

    ram = host_ram_gb if host_ram_gb is not None else host_total_memory_gb()
    if ram is None:
        ceiling = 32_768
    elif ram <= 16.5:
        ceiling = 16_384
    elif ram <= 24.5:
        ceiling = 32_768
    elif ram <= 36.5:
        ceiling = 49_152
    elif ram <= 64.5:
        ceiling = 65_536
    else:
        ceiling = 131_072

    return min(max_ctx, ceiling)
