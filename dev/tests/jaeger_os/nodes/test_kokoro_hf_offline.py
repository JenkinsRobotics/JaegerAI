"""``ensure_hf_offline_if_cached`` — 0.8.1 field bug #1: "boot never
blocks on network".

Kokoro's own loader calls ``huggingface_hub.hf_hub_download()`` with no
``local_files_only=``, so every pipeline init does an unauthenticated
HEAD request against the Hub even when every required file is already
cached — on a congested/rate-limited network that stalls boot for
minutes. ``ensure_hf_offline_if_cached`` decides offline-vs-online
BEFORE any of that happens, using only cache-index lookups (no
network). These tests mock ``huggingface_hub.try_to_load_from_cache``
so they run instantly and never touch the real cache or the network.
"""

from __future__ import annotations

import huggingface_hub
import huggingface_hub.constants as hf_constants
import pytest

from jaeger_os.nodes.kokoro_tts import engine as kokoro_engine


@pytest.fixture(autouse=True)
def _clean_hf_offline_env(monkeypatch):
    # The function under test mutates HF_HUB_OFFLINE (env + the live
    # huggingface_hub.constants module attribute) — isolate every test
    # from whatever the real process/CI environment already set, and
    # restore afterward so this suite never leaks offline mode into
    # tests that run after it.
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    orig_constant = hf_constants.HF_HUB_OFFLINE
    yield
    hf_constants.HF_HUB_OFFLINE = orig_constant


def test_forces_offline_when_every_required_file_is_cached(monkeypatch):
    monkeypatch.setattr(
        huggingface_hub, "try_to_load_from_cache",
        lambda repo_id, filename: f"/fake/cache/{filename}",
    )
    result = kokoro_engine.ensure_hf_offline_if_cached("hexgrad/Kokoro-82M", "af_heart")
    assert result is True
    import os
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert hf_constants.HF_HUB_OFFLINE is True


def test_leaves_online_and_logs_when_a_required_file_is_missing(monkeypatch, capsys):
    def _fake_lookup(repo_id, filename):
        if filename == "config.json":
            return "/fake/cache/config.json"
        return None  # voices/af_heart.pt "missing" — first-run download needed

    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache", _fake_lookup)
    result = kokoro_engine.ensure_hf_offline_if_cached("hexgrad/Kokoro-82M", "af_heart")
    assert result is False
    import os
    assert "HF_HUB_OFFLINE" not in os.environ
    err = capsys.readouterr().err
    assert "NOT fully cached" in err
    assert "voices/af_heart.pt" in err


def test_treats_the_no_exist_sentinel_as_missing(monkeypatch):
    """``try_to_load_from_cache`` can also return the ``_CACHED_NO_EXIST``
    sentinel (the Hub previously confirmed the file doesn't exist at
    this revision) — that must count as missing, same as ``None``."""
    monkeypatch.setattr(
        huggingface_hub, "try_to_load_from_cache",
        lambda repo_id, filename: huggingface_hub._CACHED_NO_EXIST,
    )
    result = kokoro_engine.ensure_hf_offline_if_cached("hexgrad/Kokoro-82M", "af_heart")
    assert result is False


def test_respects_an_operator_set_env_var_either_direction(monkeypatch):
    # Operator explicitly forced online (e.g. debugging a stale voice) —
    # never override that, even if the cache looks complete.
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    calls = []
    monkeypatch.setattr(
        huggingface_hub, "try_to_load_from_cache",
        lambda repo_id, filename: calls.append(filename) or "/fake",
    )
    result = kokoro_engine.ensure_hf_offline_if_cached("hexgrad/Kokoro-82M", "af_heart")
    assert result is False
    assert calls == []  # never even consulted the cache — env var short-circuits

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    result = kokoro_engine.ensure_hf_offline_if_cached("hexgrad/Kokoro-82M", "af_heart")
    assert result is True
    assert calls == []
