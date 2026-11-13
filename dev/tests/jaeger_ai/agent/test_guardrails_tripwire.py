"""Input/output guardrails with tripwires (standard: OpenAI Agents SDK
InputGuardrail / OutputGuardrail). Real loop, scripted adapter."""
from __future__ import annotations

import pytest

from jaeger_agent import JaegerAgent, ProviderAdapter, guardrails
from jaeger_agent.guardrails import GuardrailResult


class _Echo(ProviderAdapter):
    name = "echo"

    def __init__(self, reply="fine"):
        self.reply, self.calls = reply, 0

    def format_messages(self, messages, tools, system):  # noqa: ARG002
        return {"messages": messages}

    def call(self, formatted, interrupt_event, **kwargs):  # noqa: ARG002
        self.calls += 1
        return {"role": "assistant", "content": self.reply}

    def parse_response(self, raw):
        return raw

    def supports(self, feature):  # noqa: ARG002
        return False


@pytest.fixture(autouse=True)
def _clean():
    guardrails.clear()
    yield
    guardrails.clear()


def test_input_tripwire_stops_before_any_model_call():
    guardrails.register_input(lambda t: GuardrailResult("forbidden" in t, "test rule"), name="no_forbidden")
    adapter = _Echo()
    agent = JaegerAgent(adapter=adapter)
    out = agent.run_turn("please do the forbidden thing")
    assert adapter.calls == 0
    assert "no_forbidden input guardrail" in out
    assert agent.last_guardrail == {"stage": "input", "guardrail": "no_forbidden", "reason": "test rule"}
    assert agent.messages[-1] == {"role": "assistant", "content": out}


def test_output_tripwire_replaces_the_answer_in_the_transcript():
    guardrails.register_output(lambda t: "SECRET" in t, name="no_secret")
    agent = JaegerAgent(adapter=_Echo("here is SECRET"))
    out = agent.run_turn("hi")
    assert "no_secret output guardrail" in out and "SECRET" not in out
    assert all("here is SECRET" not in str(m.get("content")) for m in agent.messages)
    assert agent.last_guardrail["stage"] == "output"


def test_clean_turn_passes_and_broken_guardrail_fails_closed():
    agent = JaegerAgent(adapter=_Echo("fine"))
    guardrails.register_output(lambda t: None, name="noop")
    assert agent.run_turn("hi") == "fine" and agent.last_guardrail is None

    def boom(_t):
        raise RuntimeError("x")
    guardrails.register_input(boom, name="boom")
    assert "boom input guardrail" in agent.run_turn("hi")


def test_builtin_secret_leak_guardrail_and_config(tmp_path):
    from jaeger_ai.core.safety import guardrails as builtin
    cfg = tmp_path / "config.yaml"
    cfg.write_text("guardrails:\n  input:\n    block_patterns: ['rm -rf /']\n", encoding="utf-8")
    assert builtin.install(cfg) == ["output:secret_leak", "input:blocked_pattern"]
    assert guardrails.run("output", "token ghp_" + "a" * 36).guardrail == "secret_leak"
    assert guardrails.run("output", "no keys here") is None
    assert guardrails.run("input", "please RM -RF / now").guardrail == "blocked_pattern"
    guardrails.clear()
    cfg.write_text("guardrails:\n  output:\n    secret_leak: false\n", encoding="utf-8")
    assert builtin.install(cfg) == []


def test_config_schema_accepts_the_guardrails_section():
    from jaeger_ai.core.instance.schemas import GuardrailsConfig
    g = GuardrailsConfig.model_validate({"input": {"block_patterns": ["x"]}, "output": {"secret_leak": False}})
    assert g.input.block_patterns == ["x"] and g.output.secret_leak is False
