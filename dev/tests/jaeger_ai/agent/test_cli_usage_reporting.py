"""Usage/cost reporting for agent-CLI brains (standard: every model step reports
tokens and cost, as the OpenAI Agents SDK ``Usage`` / Claude Agent SDK result do).

The records below are the real tail of ``grok --output-format
streaming-messages-json`` captured on 2026-11-12 (session ids removed)."""
from __future__ import annotations

import json

from jaeger_agent.adapters.cli_backend import cli_usage

_RESULT = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 1, "result": "ok",
           "total_cost_usd": 0.02246,
           "usage": {"input_tokens": 8606, "output_tokens": 32, "cache_read_input_tokens": 10112,
                     "cache_creation_input_tokens": 0, "server_tool_use": {"web_search_requests": 0}},
           "modelUsage": {"grok-4.7-build": {"inputTokens": 8606, "outputTokens": 32, "costUSD": 0.02246}}}
_ASSISTANT = {"type": "assistant", "message": {"role": "assistant", "model": "grok-4.7",
              "content": [{"type": "text", "text": "ok"}],
              "usage": {"input_tokens": 8606, "output_tokens": 32}}}


def test_result_record_gives_usage_cost_and_model():
    out = cli_usage("\n".join([json.dumps(_ASSISTANT), json.dumps(_RESULT)]))
    assert out["usage"]["input_tokens"] == 8606 and out["usage"]["output_tokens"] == 32
    assert out["usage"]["cache_read_input_tokens"] == 10112
    assert "server_tool_use" not in out["usage"]  # nested counters are not token counts
    assert out["cost_usd"] == 0.02246 and out["model"] == "grok-4.7-build"


def test_assistant_message_usage_is_the_fallback():
    out = cli_usage(json.dumps(_ASSISTANT))
    assert out["usage"]["output_tokens"] == 32 and out["model"] == "grok-4.7" and "cost_usd" not in out


def test_plain_text_cli_reports_nothing():
    assert cli_usage("just text\n") == {}
    assert cli_usage("") == {}


def test_loop_counts_cli_usage_and_reports_cost():
    from jaeger_agent import AgentCallbacks, JaegerAgent, ProviderAdapter

    class _Cli(ProviderAdapter):
        name = "cli"

        def format_messages(self, messages, tools, system):  # noqa: ARG002
            return {"prompt": "x"}

        def call(self, formatted, interrupt_event, **kwargs):  # noqa: ARG002
            return {"stdout": "ok", "stderr": "", "returncode": 0, **cli_usage(json.dumps(_RESULT))}

        def parse_response(self, raw):
            return {"role": "assistant", "content": "ok"}

        def supports(self, feature):  # noqa: ARG002
            return False

    seen: list[dict] = []
    agent = JaegerAgent(adapter=_Cli(), callbacks=AgentCallbacks(model_call_done=seen.append))
    assert agent.run_turn("hi") == "ok"
    assert seen and seen[0]["prompt_tokens"] == 8606 + 10112 and seen[0]["completion_tokens"] == 32
    assert seen[0]["cost_usd"] == 0.02246
