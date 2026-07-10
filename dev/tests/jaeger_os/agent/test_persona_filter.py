"""Station 3 — the persona output filter.

The contracts that matter: persona-off (or any failure) is BYTE-IDENTICAL
pass-through, the prompt pins verbatim preservation, and the styled result
is sanity-checked. Design: dev/docs/reality/agentic_runners.md.
"""

from __future__ import annotations

from types import SimpleNamespace

from jaeger_os.agent.prompts.persona_filter import (
    DEFAULT_MAX_CHARS,
    apply_persona_voice,
    filter_enabled,
)

BLOCK = "You are Jarvis: dry wit, precise, quietly loyal."


class _Client:
    def __init__(self, reply="Indeed, sir — the answer is 4096."):
        self._reply = reply
        self.calls: list[dict] = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if isinstance(self._reply, Exception):
            raise self._reply
        return SimpleNamespace(text=self._reply)


def test_styles_a_normal_answer():
    c = _Client()
    out = apply_persona_voice(c, "The answer is 4096.", BLOCK)
    assert out == "Indeed, sir — the answer is 4096."
    # clean-context contract: exactly system(block) + user(rules+answer)
    msgs = c.calls[0]["messages"]
    assert msgs[0] == {"role": "system", "content": BLOCK}
    assert "VERBATIM" in msgs[1]["content"]
    assert msgs[1]["content"].endswith("The answer is 4096.")


def test_fail_open_on_exception_and_empty():
    assert apply_persona_voice(
        _Client(RuntimeError("model died")), "plain answer", BLOCK,
    ) == "plain answer"
    assert apply_persona_voice(_Client(""), "plain answer", BLOCK) == "plain answer"


def test_inflated_rewrite_is_rejected():
    c = _Client("word " * 400)  # absurdly longer than the input
    assert apply_persona_voice(c, "short answer", BLOCK) == "short answer"


def test_skips_are_byte_identical():
    c = _Client()
    halt = "[halted: hit max iterations]"
    long_answer = "x" * (DEFAULT_MAX_CHARS + 1)
    assert apply_persona_voice(c, halt, BLOCK) is halt
    assert apply_persona_voice(c, long_answer, BLOCK) is long_answer
    assert apply_persona_voice(c, "", BLOCK) == ""
    assert apply_persona_voice(c, "answer", "") == "answer"   # no character
    assert c.calls == []                                       # never called


def test_env_kill_switch(monkeypatch):
    monkeypatch.setenv("JAEGER_PERSONA_FILTER", "0")
    assert filter_enabled() is False
    c = _Client()
    assert apply_persona_voice(c, "answer", BLOCK) == "answer"
    assert c.calls == []
    monkeypatch.delenv("JAEGER_PERSONA_FILTER")
    assert filter_enabled() is True


def test_config_schema_has_persona_section():
    from jaeger_os.core.instance.schemas import Config, PersonaConfig
    pc = PersonaConfig()
    assert pc.output_filter is True and pc.max_chars == 1600
    assert Config.model_fields["persona"].default_factory is PersonaConfig


# --- Content-survival guard ------------------------------------------------
# The mechanical enforcement of "losing voice is acceptable; losing the
# answer is not": a rewrite may change every word's clothing, but it may not
# swap the content for commentary/analysis about the content (the Lilith
# bug — a joke answer came back as meta-analysis of the joke).

SCARECROW_JOKE = (
    "Why did the scarecrow win an award? Because he was outstanding in "
    "his field!"
)


def test_mangled_rewrite_analysis_instead_of_joke_returns_original():
    # The exact failure mode this guard exists for: the joke replaced by
    # meta-commentary about the joke.
    mangled = (
        "The premise suggests a pun based on the literal meaning of "
        "outstanding, contrasted with agricultural connotations, which "
        "creates the humorous incongruity."
    )
    c = _Client(mangled)
    assert apply_persona_voice(c, SCARECROW_JOKE, BLOCK) == SCARECROW_JOKE


def test_faithful_restyle_keeping_pun_words_is_returned():
    # Same joke, tone-shifted framing — the pun words survive verbatim.
    restyled = (
        "Ah, a classic for you: why did the scarecrow win an award? "
        "Because he was truly outstanding in his field, darling."
    )
    c = _Client(restyled)
    assert apply_persona_voice(c, SCARECROW_JOKE, BLOCK) == restyled


def test_short_factual_answer_restyled_passes():
    c = _Client("The port, dear fellow, is 8080.")
    out = apply_persona_voice(c, "The port is 8080.", BLOCK)
    assert out == "The port, dear fellow, is 8080."


def test_rewrite_dropping_half_the_facts_returns_original():
    original = (
        "The config is at /etc/jaeger/config.yaml, the port is 8080, and "
        "you can reach admin@example.com for access."
    )
    # Drops the path, the port, and the email — only vague framing left.
    gutted = "I looked into it and there are some details you should know."
    c = _Client(gutted)
    assert apply_persona_voice(c, original, BLOCK) == original
