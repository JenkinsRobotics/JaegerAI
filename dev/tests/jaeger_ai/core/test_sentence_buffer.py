"""Unit tests for StreamingSentenceAggregator."""

from jaeger_ai.core.voice.sentence_buffer import StreamingSentenceAggregator


def test_sentence_aggregator_single_sentence():
    agg = StreamingSentenceAggregator()
    chunks = agg.feed("Hello there, how are you today? ")
    assert chunks == ["Hello there, how are you today?"]
    assert agg.flush() == []


def test_sentence_aggregator_token_stream():
    agg = StreamingSentenceAggregator()
    tokens = ["Good ", "morning! ", "I ", "hope ", "you ", "slept ", "well. ", "Ready?"]
    received = []
    for token in tokens:
        received.extend(agg.feed(token))
    received.extend(agg.flush())

    assert received == [
        "Good morning!",
        "I hope you slept well.",
        "Ready?",
    ]


def test_sentence_aggregator_preserves_abbreviations():
    agg = StreamingSentenceAggregator()
    # "Dr. Smith went to the market. He bought 3.14 apples."
    tokens = ["Dr. ", "Smith ", "is ", "here. ", "He ", "bought ", "apples."]
    received = []
    for t in tokens:
        received.extend(agg.feed(t))
    received.extend(agg.flush())

    assert received == [
        "Dr. Smith is here.",
        "He bought apples.",
    ]


def test_sentence_aggregator_strips_think_blocks():
    agg = StreamingSentenceAggregator()
    tokens = ["<think>Thinking about what to say</think>Hello ", "world!"]
    received = []
    for t in tokens:
        received.extend(agg.feed(t))
    received.extend(agg.flush())

    assert received == ["Hello world!"]
