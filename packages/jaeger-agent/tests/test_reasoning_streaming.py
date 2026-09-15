"""Reasoning is a live channel, not a summary appended after the answer.

Every reasoning-model API streams deliberation on its own channel while it is
produced — OpenAI's o-series ``reasoning``, DeepSeek-R1's ``reasoning_content``,
Anthropic's thinking blocks. Surfaces render it in a "thinking" block that
fills as it arrives and settles when the answer starts.

This adapter collected reasoning deltas into a list and emitted the finished
block only after the model step returned, so a surface received the entire
answer BEFORE any of the thinking behind it. The chat window showed the reply,
then a thought bubble underneath explaining reasoning that had supposedly come
first.
"""
from __future__ import annotations

import threading

from jaeger_agent.adapters.openai import _aggregate_chat_stream


class _Delta:
    def __init__(self, content=None, reasoning=None):
        self.content = content
        self.reasoning = reasoning
        self.reasoning_content = None
        self.tool_calls = []


class _Chunk:
    def __init__(self, **kw):
        self.choices = [type("C", (), {"delta": _Delta(**kw), "finish_reason": None})()]
        self.usage = None


class _Progress:
    def tick(self, *a, **k): pass
    def note(self, *a, **k): pass
    def __getattr__(self, _name): return lambda *a, **k: None


def _drain(chunks, **sinks):
    return _aggregate_chat_stream(iter(chunks), threading.Event(), _Progress(), **sinks)


def test_reasoning_streams_before_the_answer_it_produced() -> None:
    """The ordering that was wrong: thinking must arrive with, not after, text."""
    order: list[tuple[str, str]] = []
    _drain(
        [_Chunk(reasoning="thinking about it"),
         _Chunk(content="the "), _Chunk(content="answer")],
        on_delta=lambda t: order.append(("text", t)),
        on_reasoning=lambda t: order.append(("reasoning", t)),
    )
    assert order[0] == ("reasoning", "thinking about it"), (
        f"reasoning did not arrive first: {order}"
    )
    assert [k for k, _ in order] == ["reasoning", "text", "text"]


def test_reasoning_arrives_chunk_by_chunk() -> None:
    """Not one block at the end — a thinking panel has to fill as it goes."""
    got: list[str] = []
    _drain([_Chunk(reasoning="one"), _Chunk(reasoning="two"), _Chunk(content="x")],
           on_reasoning=got.append)
    assert got == ["one", "two"]


def test_interleaved_reasoning_keeps_its_place() -> None:
    """A model that thinks again mid-answer must show it there, not at the end."""
    order: list[str] = []
    _drain(
        [_Chunk(reasoning="first"), _Chunk(content="a"),
         _Chunk(reasoning="second"), _Chunk(content="b")],
        on_delta=lambda t: order.append(f"text:{t}"),
        on_reasoning=lambda t: order.append(f"reason:{t}"),
    )
    assert order == ["reason:first", "text:a", "reason:second", "text:b"]


def test_the_aggregated_result_is_unchanged() -> None:
    """Streaming is additive: the returned message must still carry both."""
    out = _drain([_Chunk(reasoning="why"), _Chunk(content="what")])
    message = out["choices"][0]["message"]
    assert message["content"] == "what"
    assert "why" in (message.get("reasoning") or "")


def test_no_sink_means_no_callback_cost() -> None:
    """Callers that aren't listening must not pay per-chunk."""
    out = _drain([_Chunk(reasoning="r"), _Chunk(content="c")])
    assert out["choices"][0]["message"]["content"] == "c"


def test_streamed_reasoning_is_not_emitted_twice() -> None:
    """The post-step fallback must stay quiet once the adapter has streamed.

    Both paths firing would render the same deliberation twice — once live,
    once as a block under the answer.
    """
    from jaeger_agent.loop.jaeger_agent import JaegerAgent
    import inspect

    source = inspect.getsource(JaegerAgent)
    assert "_streamed_reasoning" in source
    assert "not self._streamed_reasoning" in source, (
        "the post-step reasoning fallback no longer checks whether the adapter "
        "already streamed it; the thinking will appear twice"
    )
