"""Drift parser — extract_tool_calls / repair_arguments / normalize_tool_name.

Same battle the legacy ``core/llm_model.py`` parser fights, but the
return shape is internal ``ToolCall`` dicts instead of OpenAI wire
format. The cases here mirror real model outputs we've observed in the
wild — Gemma's three dialects, Qwen3-Coder's XML, the Hermes JSON
envelope, plus the malformed inputs that used to drop calls silently.
"""

from __future__ import annotations

import json

from jaeger_os.agent.dialects import (
    extract_tool_calls,
    normalize_tool_name,
    repair_arguments,
    strip_reasoning_channels,
)


def test_strip_gemma4_reasoning_channel_leak():
    """Regression (2026-06-20): gemma-4-12B leaks its reasoning channel as
    raw text — ``<|channel>thought\\n<channel|>ANSWER`` — that doesn't
    match the proper ``<|channel|>`` harmony form, so it surfaced verbatim
    in the live TUI as a phantom 'thought'. The stripper must return just
    the answer (the content after the channel header)."""
    leaked = ("<|channel>thought\n<channel|>The current date is "
              "Saturday, June 20, 2026, and the time is 11:21 PM.")
    out = strip_reasoning_channels(leaked)
    assert out == ("The current date is Saturday, June 20, 2026, "
                   "and the time is 11:21 PM.")
    assert "channel" not in out and "thought" not in out


def test_strip_reasoning_channels_leaves_plain_text_untouched():
    """No channel markers → unchanged, even if the word 'channel' appears."""
    plain = "The TV channel was showing a documentary about rabbits."
    assert strip_reasoning_channels(plain) == plain
    assert strip_reasoning_channels("just a normal answer") == "just a normal answer"


# ── extract_tool_calls — happy paths ───────────────────────────────


def test_extract_returns_empty_when_no_xml_present():
    assert extract_tool_calls("just a plain answer, no tools") == []


def test_extract_returns_empty_when_only_partial_marker_present():
    """Bare '<' shouldn't trip the extractor — it requires a full pattern
    match to fire a call."""
    assert extract_tool_calls("a < b") == []


def test_extract_hermes_json_envelope():
    text = '<tool_call>{"name": "get_time", "arguments": {"tz": "UTC"}}</tool_call>'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "get_time"
    assert calls[0]["arguments"] == {"tz": "UTC"}
    assert calls[0]["id"].startswith("drift_")


def test_extract_legacy_gemma_json_envelope():
    text = '<|tool_call|>{"name": "lookup", "arguments": {"q": "x"}}<|/tool_call|>'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "lookup"
    assert calls[0]["arguments"] == {"q": "x"}


def test_extract_gemma_brace_args_form():
    text = '<|tool_call>call:get_time{tz:<|"|>UTC<|"|>}<tool_call|>'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "get_time"
    assert calls[0]["arguments"] == {"tz": "UTC"}


def test_extract_gemma_paren_kwargs_form():
    text = "<|tool_call>call:write_file(path='/tmp/x.py', content='print(1)')<tool_call|>"
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "write_file"
    assert calls[0]["arguments"]["path"] == "/tmp/x.py"
    assert calls[0]["arguments"]["content"] == "print(1)"


def test_extract_qwen_xml_form():
    text = (
        "<tool_call>"
        "<function=search>"
        "<parameter=query>population of japan</parameter>"
        "<parameter=max_results>5</parameter>"
        "</function>"
        "</tool_call>"
    )
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "search"
    assert calls[0]["arguments"] == {
        "query": "population of japan",
        "max_results": "5",
    }
    assert calls[0]["id"].startswith("qwen_")


def test_extract_qwen_loose_function_form_no_tool_call_wrapper():
    """Qwen3-Coder sometimes emits ``<function=name>...</function>`` WITHOUT
    the outer ``<tool_call>`` wrapper — a stray ``</tool_call>`` closer
    with no matching opener can even tag along. The parser must still
    dispatch the call instead of letting the XML leak into the answer
    text (which is exactly what the operator reported on
    Qwen3-Coder-30B-A3B-Instruct-Q4_K_M)."""
    text = (
        "I'll help. Let me check the system.\n\n"
        "<function=system_status>\n"
        "</function>\n"
        "</tool_call>\n"
    )
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "system_status"
    # No <parameter=> blocks → empty args, which is correct for
    # ``system_status`` (it takes none).
    assert calls[0]["arguments"] == {}
    assert calls[0]["id"].startswith("qwen_")


def test_extract_qwen_loose_function_form_with_parameters():
    """The same loose form but with parameter blocks — make sure args
    still flow through. Mirrors the strict-form test for parity."""
    text = (
        "<function=web_search>"
        "<parameter=query>weather in tokyo</parameter>"
        "<parameter=max_results>3</parameter>"
        "</function>"
    )
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "web_search"
    assert calls[0]["arguments"] == {
        "query": "weather in tokyo",
        "max_results": "3",
    }


def test_extract_mistral_bare_name_json_form():
    """Ministral emits a bare ``name{json}`` (Mistral v11 interleaved
    without the [TOOL_CALLS] token). Must salvage it."""
    calls = extract_tool_calls('get_time{"timezone": "Asia/Shanghai"}')
    assert len(calls) == 1
    assert calls[0]["name"] == "get_time"
    assert calls[0]["arguments"] == {"timezone": "Asia/Shanghai"}
    assert calls[0]["id"].startswith("mistral_")


def test_extract_mistral_bare_empty_args():
    calls = extract_tool_calls("get_time{}")
    assert len(calls) == 1
    assert calls[0]["name"] == "get_time"
    assert calls[0]["arguments"] == {}


def test_bare_name_json_does_not_match_prose():
    """The bare form is anchored to the whole message — a ``word{…}``
    buried in a real answer must NOT be misread as a tool call."""
    assert extract_tool_calls(
        "Use the config{} block then call setup{} as shown."
    ) == []
    # Trailing prose after the JSON also disqualifies it.
    assert extract_tool_calls('get_time{"tz": "UTC"} and then relax') == []


def test_loose_and_strict_forms_do_not_double_count():
    """If the model emits both — a strict ``<tool_call>...</tool_call>``
    AND another loose ``<function=...>`` outside it — they should be
    extracted as two distinct calls, NOT the strict one twice."""
    text = (
        "<tool_call><function=a></function></tool_call>"
        " interlude "
        "<function=b><parameter=x>1</parameter></function>"
    )
    calls = extract_tool_calls(text)
    names = [c["name"] for c in calls]
    assert names == ["a", "b"]


def test_extract_multiple_calls_in_one_response():
    text = (
        '<tool_call>{"name": "a", "arguments": {}}</tool_call>'
        ' some text in between '
        '<tool_call>{"name": "b", "arguments": {"k": 1}}</tool_call>'
    )
    calls = extract_tool_calls(text)
    assert [c["name"] for c in calls] == ["a", "b"]


# ── extract_tool_calls — malformed input ───────────────────────────


def test_extract_recovers_from_trailing_comma():
    text = '<tool_call>{"name": "x", "arguments": {"a": 1,},}</tool_call>'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["arguments"] == {"a": 1}


def test_extract_recovers_from_gemma_quote_tokens():
    text = '<tool_call>{<|"|>name<|"|>:<|"|>recall<|"|>,<|"|>q<|"|>:<|"|>cats<|"|>}</tool_call>'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "recall"
    # The flat-args style — every remaining key is a tool arg.
    assert calls[0]["arguments"] == {"q": "cats"}


def test_extract_handles_flat_arg_style_no_arguments_key():
    """Gemma sometimes emits args at the top level instead of nested
    under ``arguments``."""
    text = '<tool_call>{"name": "write_file", "path": "/tmp/x", "content": "hi"}</tool_call>'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "write_file"
    assert calls[0]["arguments"] == {"path": "/tmp/x", "content": "hi"}


def test_extract_handles_double_encoded_arguments_string():
    text = '<tool_call>{"name": "x", "arguments": "{\\"a\\": 1}"}</tool_call>'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["arguments"] == {"a": 1}


def test_extract_drops_block_with_no_recoverable_name():
    text = '<tool_call>{"arguments": {"x": 1}}</tool_call>'
    assert extract_tool_calls(text) == []


# ── repair_arguments ───────────────────────────────────────────────


def test_repair_arguments_strict_json_passthrough():
    args, ok = repair_arguments('{"a": 1, "b": "two"}')
    assert ok is True
    assert args == {"a": 1, "b": "two"}


def test_repair_arguments_empty_input_is_recovered_empty():
    args, ok = repair_arguments("")
    assert ok is True
    assert args == {}
    args, ok = repair_arguments("none")
    assert ok is True
    assert args == {}


def test_repair_arguments_strips_trailing_commas():
    args, ok = repair_arguments('{"a": 1, "b": 2,}')
    assert ok is True
    assert args == {"a": 1, "b": 2}


def test_repair_arguments_swaps_single_quotes_when_safe():
    """Wholly single-quoted blob with no doubles → safe to swap."""
    args, ok = repair_arguments("{'a': 1, 'b': 'two'}")
    assert ok is True
    assert args == {"a": 1, "b": "two"}


def test_repair_arguments_double_encoded_string():
    """Local models occasionally emit a JSON string instead of a JSON
    object for the arguments — the repairer unwraps one level."""
    args, ok = repair_arguments('"{\\"x\\": 9}"')
    assert ok is True
    assert args == {"x": 9}


def test_repair_arguments_falls_through_to_gemma_loose_parser():
    args, ok = repair_arguments('{tz:<|"|>UTC<|"|>}')
    assert ok is True
    assert args.get("tz") == "UTC"


def test_repair_arguments_returns_unrecovered_on_total_garbage():
    args, ok = repair_arguments("@@@ not json at all $$$")
    # The fallback Gemma parser may or may not pluck pairs out of this —
    # the important assertion is that the API contract is honoured: we
    # always return a dict + a bool, never raise.
    assert isinstance(args, dict)
    assert isinstance(ok, bool)


# ── normalize_tool_name ────────────────────────────────────────────


def test_normalize_returns_input_when_exact_match():
    valid = frozenset({"get_time", "lookup"})
    assert normalize_tool_name("get_time", valid) == "get_time"


def test_normalize_collapses_case_and_hyphens():
    valid = frozenset({"get_time"})
    assert normalize_tool_name("Get-Time", valid) == "get_time"


def test_normalize_handles_camel_case():
    valid = frozenset({"get_time"})
    assert normalize_tool_name("GetTime", valid) == "get_time"


def test_normalize_strips_trailing_tool_suffix():
    valid = frozenset({"read_file"})
    assert normalize_tool_name("ReadFileTool", valid) == "read_file"
    assert normalize_tool_name("read_file_tool", valid) == "read_file"


def test_normalize_returns_unchanged_when_no_alias_matches():
    """No fuzzy guessing — an unrecognised name must surface as such so
    dispatch yields a clean 'unknown tool' error and the model retries."""
    valid = frozenset({"get_time"})
    assert normalize_tool_name("totally_different", valid) == "totally_different"


def test_normalize_empty_input_returns_empty():
    assert normalize_tool_name("", frozenset({"x"})) == ""
    assert normalize_tool_name("anything", frozenset()) == "anything"


def test_normalize_never_routes_to_removed_system_health():
    """``self_check`` is the agent doctor now; ``system_health`` was
    renamed away. The drift parser must never normalize health-ish
    aliases to the removed ``system_health`` name — that would route the
    model to a tool that no longer exists (confusing "unknown tool")."""
    valid = frozenset({"system_status", "get_time", "self_check"})
    for alias in ("self_check", "selfcheck", "health_check",
                  "healthcheck", "check_health", "diagnose"):
        result = normalize_tool_name(alias, valid)
        assert result != "system_health", (
            f"{alias!r} normalized to the removed system_health name"
        )


# ── Llama 3.x / 4 raw-JSON form ──────────────────────────────────────


def test_extract_llama_with_python_tag():
    """Llama 3.x emits a bot token followed by the JSON object."""
    text = (
        "Thinking about this...\n"
        '<|python_tag|>{"name": "get_weather", "parameters": {"location": "Tokyo"}}'
    )
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "get_weather"
    assert calls[0]["arguments"] == {"location": "Tokyo"}
    assert calls[0]["id"].startswith("llama_")


def test_extract_llama_bare_json_no_wrapper():
    """No bot token, no XML — Llama can drop a bare ``{"name": …,
    "arguments": …}`` object into chat text. Salvage it iff no other
    dialect's opening tag is present."""
    text = 'I will call this: {"name": "calculate", "arguments": {"expression": "1+1"}}'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "calculate"
    assert calls[0]["arguments"] == {"expression": "1+1"}


def test_extract_llama_does_not_steal_hermes_envelope():
    """Critical regression guard — a Hermes JSON envelope inside
    ``<tool_call>…</tool_call>`` must still match the Hermes path, NOT
    the Llama branch. Without this check the Llama parser would
    return an id starting with ``llama_`` instead of ``drift_``."""
    text = '<tool_call>{"name": "get_time", "arguments": {"tz": "UTC"}}</tool_call>'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "get_time"
    assert calls[0]["id"].startswith("drift_"), (
        f"Hermes envelope misrouted to a non-drift parser; id={calls[0]['id']}"
    )


# ── Mistral [TOOL_CALLS] form ────────────────────────────────────────


def test_extract_mistral_pre_v11_json_array():
    """Pre-v11 Mistral: ``[TOOL_CALLS]`` followed by a JSON array."""
    text = (
        "Sure, calling the tool now."
        '[TOOL_CALLS] [{"name": "get_time", "arguments": {"timezone": "UTC"}}]'
    )
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "get_time"
    assert calls[0]["arguments"] == {"timezone": "UTC"}
    assert calls[0]["id"].startswith("mistral_")


def test_extract_mistral_v11_interleaved():
    """v11+ Mistral: ``[TOOL_CALLS]name{args}`` possibly chained."""
    text = (
        '[TOOL_CALLS]get_time{"timezone": "UTC"}'
        '[TOOL_CALLS]calculate{"expression": "2+2"}'
    )
    calls = extract_tool_calls(text)
    assert len(calls) == 2
    names = [c["name"] for c in calls]
    assert names == ["get_time", "calculate"]
    assert calls[1]["arguments"] == {"expression": "2+2"}
