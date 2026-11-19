from jaeger_agent.loop.runtime_bridge import is_routine_lookup_turn


def test_narrow_live_lookups_use_compact_prompt():
    assert is_routine_lookup_turn("How many chat sessions do I have? Use the authoritative session tool.")
    assert is_routine_lookup_turn("Show installed models")
    assert is_routine_lookup_turn("What is the gateway health?")


def test_short_agentic_work_keeps_full_prompt():
    assert not is_routine_lookup_turn("Research the best local coding model")
    assert not is_routine_lookup_turn("Fix the gateway latency")
    assert not is_routine_lookup_turn("Remember my preferred model")
    assert not is_routine_lookup_turn("Write a Python function and test it")
    assert not is_routine_lookup_turn("Decide which model Jaeger should use")
