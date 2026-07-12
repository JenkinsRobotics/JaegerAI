"""Runtime inventory — what local inference engines are installed and reachable.

Surfaces the same one-screen view LM Studio's Settings → Runtime panel
gives: each engine's display name, version, install/reach state, the
model formats it loads, and a one-line description. The ``/runtime``
slash command renders this so the user can tell at a glance which
engines are present, which are missing, and what each runtime is for.

The four runtimes Jaeger cares about:

  • ``llama-cpp-python`` — GGUF, in-process, Apple Metal accelerated.
    Pip wheel; version from ``llama_cpp.__version__``.
  • ``mlx-lm`` — Apple MLX engine for Apple Silicon, MLX-format models.
    Pip wheel; absent on Jaeger's default install.
  • Ollama — HTTP server on localhost:11434. Loads GGUF.
  • LM Studio — HTTP server on localhost:1234. Loads GGUF + MLX.

What this module is *not*: a multi-version install / switch system. LM
Studio carries side-by-side ``llama.cpp`` builds with a ``latest``
symlink (the panel screenshot shows v2.5.1 / 2.12.0 / 2.13.0 / 2.14.0 /
2.16.0). Jaeger pins one ``llama-cpp-python`` wheel into its venv;
switching between pinned versions is a separate engineering project
(per-version venv isolation, dynamic load, the works) that should not
be smuggled in here.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

_PROBE_TIMEOUT_S = 1.0


@dataclass(frozen=True)
class Runtime:
    """One inference engine — installed or not."""

    name: str                       # stable id, e.g. "llama-cpp-python"
    display_name: str               # what the user sees, e.g. "Metal llama.cpp"
    version: str | None             # None when not installed / not reachable
    available: bool
    description: str
    formats: tuple[str, ...]        # model file formats this engine loads
    install_hint: str | None = None  # filled when not available


def _import_version(module_name: str) -> str | None:
    """Best-effort ``__version__`` from a module — None when not importable."""
    try:
        mod = __import__(module_name)
        version = getattr(mod, "__version__", None)
        return str(version) if version else "installed"
    except ImportError:
        return None
    except Exception:  # noqa: BLE001 — never propagate from inventory
        return None


def _probe_http(url: str, timeout: float = _PROBE_TIMEOUT_S) -> bytes | None:
    """GET ``url`` and return the body, or None on any failure."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if 200 <= resp.status < 300:
                return resp.read(8192)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
        return None
    except Exception:  # noqa: BLE001
        return None
    return None


def discover_llama_cpp_python() -> Runtime:
    """The in-process GGUF engine Jaeger's local backend uses."""
    version = _import_version("llama_cpp")
    return Runtime(
        name="llama-cpp-python",
        display_name="Metal llama.cpp",
        version=version,
        available=version is not None,
        description="GGUF in-process, Apple Metal accelerated.",
        formats=(".gguf",),
        install_hint=None if version else "pip install llama-cpp-python",
    )


def discover_mlx() -> Runtime:
    """Apple's MLX engine — separate pip wheel, not bundled by default."""
    version = _import_version("mlx_lm") or _import_version("mlx")
    # When the wheel is installed AND there are MLX models on disk, surface
    # the count alongside the version so the panel mirrors LM Studio's
    # "(N models)" hint.
    description = "Apple Silicon MLX engine — MLX-format models."
    if version is not None:
        try:
            from jaeger_ai.core.models.model_discovery import discover_local_mlx
            n = len(discover_local_mlx())
            if n:
                description = (
                    f"Apple Silicon MLX engine — {n} model"
                    f"{'s' if n != 1 else ''} on disk."
                )
        except Exception:  # noqa: BLE001
            pass
    return Runtime(
        name="mlx-lm",
        display_name="Apple MLX",
        version=version,
        available=version is not None,
        description=description,
        formats=("MLX (safetensors)",),
        install_hint=None if version else "pip install mlx-lm",
    )


def discover_ollama() -> Runtime:
    body = _probe_http("http://localhost:11434/api/version")
    version: str | None = None
    if body is not None:
        try:
            version = str(json.loads(body).get("version") or "running")
        except (json.JSONDecodeError, TypeError, AttributeError):
            version = "running"
    return Runtime(
        name="ollama",
        display_name="Ollama",
        version=version,
        available=version is not None,
        description="HTTP server (localhost:11434). GGUF via /api/chat.",
        formats=(".gguf",),
        install_hint=None if version else "brew install ollama && ollama serve",
    )


def discover_lmstudio() -> Runtime:
    """LM Studio's local OpenAI-compatible server — covers GGUF + MLX."""
    reachable = _probe_http("http://localhost:1234/v1/models") is not None
    return Runtime(
        name="lmstudio",
        display_name="LM Studio",
        version="running" if reachable else None,
        available=reachable,
        description="HTTP server (localhost:1234). GGUF + MLX via LM Studio.",
        formats=(".gguf", "MLX (safetensors)"),
        install_hint=None if reachable else "Install LM Studio + start the server",
    )


def discover_runtimes() -> list[Runtime]:
    """All four engines in display order — installed first, then reachable
    servers, then missing entries with install hints."""
    return [
        discover_llama_cpp_python(),
        discover_mlx(),
        discover_ollama(),
        discover_lmstudio(),
    ]
