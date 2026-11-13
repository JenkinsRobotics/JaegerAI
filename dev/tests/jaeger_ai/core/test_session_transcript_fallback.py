"""Session memory survives a failed memory enrichment (prepare_turn)."""
from jaeger_ai.core.gateway.server import _with_transcript_fallback


def test_fallback_carries_prior_turns_without_the_current_message():
    session = {"messages": [
        {"id": 1, "role": "user", "content": "My codeword is PELICAN-42."},
        {"id": 2, "role": "assistant", "content": "noted."},
        {"id": 3, "role": "user", "content": "What was my codeword?"},
    ]}
    prompt = _with_transcript_fallback("What was my codeword?", session)
    assert "PELICAN-42" in prompt
    assert prompt.endswith("What was my codeword?")
    assert prompt.count("What was my codeword?") == 1


def test_no_history_returns_the_bare_request():
    assert _with_transcript_fallback("hi", {"messages": [{"role": "user", "content": "hi"}]}) == "hi"
    assert _with_transcript_fallback("hi", None) == "hi"
