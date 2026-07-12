"""Recently-used external models — per-provider history file.

The /model picker pre-populates each cloud provider's sub-menu with the
models the user has switched to before, so a one-off paste of
``qwen3.5:397b`` becomes a one-click pick next time.
"""

from __future__ import annotations

from types import SimpleNamespace

from jaeger_ai.core.models.external_model_history import (
    _MAX_PER_PROVIDER,
    load_history,
    recent_models,
    record_use,
)


def _layout(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(memory_dir=memory_dir)


def test_record_use_then_recall_returns_latest_first(tmp_path):
    layout = _layout(tmp_path)
    record_use(layout, "ollama-cloud", "qwen3.5:397b")
    record_use(layout, "ollama-cloud", "gpt-oss:120b")
    assert recent_models(layout, "ollama-cloud") == ["gpt-oss:120b", "qwen3.5:397b"]


def test_record_use_deduplicates_against_prior_entries(tmp_path):
    """Re-recording an existing model moves it to the front, doesn't double it."""
    layout = _layout(tmp_path)
    record_use(layout, "ollama-cloud", "qwen3.5:397b")
    record_use(layout, "ollama-cloud", "gpt-oss:120b")
    record_use(layout, "ollama-cloud", "qwen3.5:397b")
    assert recent_models(layout, "ollama-cloud") == [
        "qwen3.5:397b", "gpt-oss:120b",
    ]


def test_history_is_per_provider(tmp_path):
    layout = _layout(tmp_path)
    record_use(layout, "ollama-cloud", "qwen3.5:397b")
    record_use(layout, "openai", "gpt-4o")
    assert recent_models(layout, "ollama-cloud") == ["qwen3.5:397b"]
    assert recent_models(layout, "openai") == ["gpt-4o"]
    assert recent_models(layout, "anthropic") == []


def test_history_caps_per_provider(tmp_path):
    layout = _layout(tmp_path)
    for i in range(_MAX_PER_PROVIDER + 5):
        record_use(layout, "openai", f"gpt-{i}")
    history = load_history(layout)["openai"]
    assert len(history) == _MAX_PER_PROVIDER
    # The newest survive; the oldest were evicted.
    assert history[0] == f"gpt-{_MAX_PER_PROVIDER + 4}"


def test_recent_models_respects_limit(tmp_path):
    layout = _layout(tmp_path)
    for i in range(5):
        record_use(layout, "gemini", f"model-{i}")
    assert recent_models(layout, "gemini", limit=2) == ["model-4", "model-3"]


def test_missing_file_returns_empty(tmp_path):
    layout = _layout(tmp_path)
    assert load_history(layout) == {}
    assert recent_models(layout, "ollama-cloud") == []


def test_corrupt_file_returns_empty_not_raises(tmp_path):
    layout = _layout(tmp_path)
    (layout.memory_dir / "external_model_history.json").write_text("not json{{", encoding="utf-8")
    assert load_history(layout) == {}
    # And a subsequent record_use overwrites cleanly.
    record_use(layout, "openai", "gpt-4o")
    assert recent_models(layout, "openai") == ["gpt-4o"]


def test_record_use_no_ops_on_empty_inputs(tmp_path):
    layout = _layout(tmp_path)
    record_use(layout, "", "model")
    record_use(layout, "openai", "")
    assert load_history(layout) == {}
