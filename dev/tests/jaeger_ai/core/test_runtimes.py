"""Runtime inventory — what local inference engines are present.

The /runtime slash command surfaces this list LM-Studio-style. These
tests cover the pure-data helpers; the HTTP probes are mocked so the
suite never depends on a running Ollama / LM Studio.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from jaeger_ai.core.models.runtimes import (
    Runtime,
    _import_version,
    discover_llama_cpp_python,
    discover_lmstudio,
    discover_mlx,
    discover_ollama,
    discover_runtimes,
)


# ── version introspection ───────────────────────────────────────────


def test_import_version_returns_string_for_installed_module():
    """``json`` ships with the stdlib — _import_version must surface
    *something* truthy for it."""
    assert _import_version("json")  # has no __version__, falls back to "installed"


def test_import_version_returns_none_for_missing_module():
    assert _import_version("definitely_not_a_real_module_xyz") is None


# ── individual runtime probes ───────────────────────────────────────


def test_discover_llama_cpp_python_reflects_install_state():
    rt = discover_llama_cpp_python()
    assert isinstance(rt, Runtime)
    assert rt.name == "llama-cpp-python"
    assert rt.display_name == "Metal llama.cpp"
    assert ".gguf" in rt.formats
    # Whether available or not, the contract is consistent.
    if rt.available:
        assert rt.version
        assert rt.install_hint is None
    else:
        assert rt.version is None
        assert "pip install" in (rt.install_hint or "")


def test_discover_mlx_offers_install_hint_when_absent():
    rt = discover_mlx()
    assert rt.name == "mlx-lm"
    if not rt.available:
        assert "mlx-lm" in (rt.install_hint or "")


# ── HTTP-probed runtimes (Ollama / LM Studio) ───────────────────────


def test_discover_ollama_when_server_responds():
    fake_body = json.dumps({"version": "0.4.5"}).encode()
    fake_resp = type("R", (), {"status": 200, "read": lambda self, _: fake_body})()
    fake_cm = type("CM", (), {
        "__enter__": lambda self: fake_resp,
        "__exit__": lambda self, *a: False,
    })()
    with patch("jaeger_ai.core.models.runtimes.urllib.request.urlopen", return_value=fake_cm):
        rt = discover_ollama()
    assert rt.available is True
    assert rt.version == "0.4.5"
    assert ".gguf" in rt.formats


def test_discover_ollama_when_server_unreachable():
    import urllib.error
    with patch(
        "jaeger_ai.core.models.runtimes.urllib.request.urlopen",
        side_effect=urllib.error.URLError("conn refused"),
    ):
        rt = discover_ollama()
    assert rt.available is False
    assert rt.version is None
    assert "ollama" in (rt.install_hint or "").lower()


def test_discover_lmstudio_when_server_responds():
    fake_resp = type("R", (), {"status": 200, "read": lambda self, _: b"{}"})()
    fake_cm = type("CM", (), {
        "__enter__": lambda self: fake_resp,
        "__exit__": lambda self, *a: False,
    })()
    with patch("jaeger_ai.core.models.runtimes.urllib.request.urlopen", return_value=fake_cm):
        rt = discover_lmstudio()
    assert rt.available is True
    assert rt.version == "running"
    # LM Studio's server can host MLX too.
    assert any("MLX" in f for f in rt.formats)


def test_discover_lmstudio_when_server_unreachable():
    import urllib.error
    with patch(
        "jaeger_ai.core.models.runtimes.urllib.request.urlopen",
        side_effect=urllib.error.URLError("conn refused"),
    ):
        rt = discover_lmstudio()
    assert rt.available is False
    assert "LM Studio" in (rt.install_hint or "")


# ── aggregator ──────────────────────────────────────────────────────


def test_discover_runtimes_returns_all_four_in_stable_order():
    import urllib.error
    with patch(
        "jaeger_ai.core.models.runtimes.urllib.request.urlopen",
        side_effect=urllib.error.URLError("offline"),
    ):
        runtimes = discover_runtimes()
    assert [rt.name for rt in runtimes] == [
        "llama-cpp-python", "mlx-lm", "ollama", "lmstudio",
    ]
    # Every Runtime has the contract fields filled.
    for rt in runtimes:
        assert rt.display_name
        assert rt.description
        assert rt.formats
        assert isinstance(rt.available, bool)
