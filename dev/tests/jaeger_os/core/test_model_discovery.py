"""Model discovery + the Ollama provider.

Discovery surveys three sources (JROS registry / Ollama / LM Studio) so
the TUI's /model command can show the full picture; a server that is
not running must report offline, never raise. Ollama is a new external
provider that rides the OpenAI-compatible path.
"""

from __future__ import annotations

from jaeger_os.core.models.external_model import _OPENAI_COMPATIBLE
from jaeger_os.core.models.model_discovery import (
    discover_all,
    discover_jaeger,
    discover_lmstudio,
    discover_ollama,
)
from jaeger_os.core.instance.schemas import ExternalModelConfig


# ── Ollama provider ──────────────────────────────────────────────────


def test_ollama_is_a_valid_provider() -> None:
    cfg = ExternalModelConfig(provider="ollama")
    assert cfg.provider == "ollama"


def test_ollama_rides_the_openai_compatible_path() -> None:
    # Ollama speaks OpenAI-compatible HTTP — no separate client needed.
    assert "ollama" in _OPENAI_COMPATIBLE
    assert "lmstudio" in _OPENAI_COMPATIBLE


# ── discovery ────────────────────────────────────────────────────────


def test_discover_jaeger_lists_the_registry() -> None:
    models = discover_jaeger()
    assert isinstance(models, list)
    assert any(m.get("name") for m in models)        # gemma / qwen registered


def test_offline_server_probe_is_graceful() -> None:
    # A port nothing listens on — must report offline cleanly, not raise.
    r = discover_ollama("http://localhost:9")
    assert r["online"] is False and r["models"] == []
    r2 = discover_lmstudio("http://localhost:9")
    assert r2["online"] is False and r2["models"] == []


def test_discover_all_covers_every_source() -> None:
    d = discover_all()
    assert set(d) == {
        "jaeger", "local_gguf", "local_mlx", "ollama", "lmstudio", "ollama_cloud",
    }
    assert isinstance(d["jaeger"], list)
    assert isinstance(d["local_gguf"], list)
    assert isinstance(d["local_mlx"], list)
    for src in ("ollama", "lmstudio", "ollama_cloud"):
        assert "online" in d[src] and "models" in d[src]


def test_ollama_cloud_offline_without_a_key() -> None:
    from jaeger_os.core.models.model_discovery import discover_ollama_cloud
    r = discover_ollama_cloud("")
    assert r["online"] is False and r["models"] == []


def test_local_gguf_discovery_is_a_filesystem_scan() -> None:
    # discover_local_gguf returns disk .gguf files with name/path/source
    # and never raises, even if no model dir exists.
    from jaeger_os.core.models.model_discovery import discover_local_gguf
    out = discover_local_gguf()
    assert isinstance(out, list)
    for m in out:
        assert m["name"].endswith(".gguf")
        assert m["path"] and m["source"]


def test_ollama_disk_discovery_skips_os_noise() -> None:
    from jaeger_os.core.models.model_discovery import discover_ollama_disk
    out = discover_ollama_disk()
    assert isinstance(out, list)
    # .DS_Store / hidden files must never leak in as "models".
    assert all(not m["name"].endswith(".DS_Store") for m in out)
    assert all(not m["name"].startswith(".") for m in out)
