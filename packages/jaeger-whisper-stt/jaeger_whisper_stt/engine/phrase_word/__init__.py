"""phrase_word — ``continuous`` finals plus live partials.

Precursor: MockingAgent
``PywisperCpp/pywhispercpp_examples/llm_listener/always_listening_hybrid_phrase_word_pipeline.py``.
The live adapter is in ``pipeline.py``; ``bench()`` is the perf probe.
"""

from .pipeline import WhisperSTTPhraseWord

__all__ = ["WhisperSTTPhraseWord", "bench"]


def bench(audio, sr, ref=None, *, model="base.en"):
    """Identical work to ``continuous`` — one model, one pass.  Emitting
    partials costs nothing the bench can see, so the number is the
    continuous number under this method's name."""
    from ..continuous import bench as continuous_bench
    r = continuous_bench(audio, sr, ref, model=model)
    r.method = "phrase_word"
    return r
