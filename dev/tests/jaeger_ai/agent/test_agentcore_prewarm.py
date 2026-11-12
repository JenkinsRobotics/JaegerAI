"""KV-prewarm is decoupled from voice-model warmup.

The windowed app boots with warmup=False to skip the heavy whisper/kokoro
preloads — but it must STILL prewarm the LLM (system prompt + tool schemas) so
the first user turn isn't a ~26s cold prefill. Regression guard so the two
never get re-coupled.
"""

import inspect


def test_boot_for_tui_exposes_prewarm_model() -> None:
    from jaeger_ai.main import boot_for_tui
    assert "prewarm_model" in inspect.signature(boot_for_tui).parameters


