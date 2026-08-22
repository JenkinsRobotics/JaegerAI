"""continuous — one model + rolling re-transcription, via pywhispercpp.
The live adapter is in ``pipeline.py``; ``bench()`` is the perf probe.
"""

from .pipeline import WhisperSTTContinuous

__all__ = ["WhisperSTTContinuous", "bench"]


def bench(audio, sr, ref=None, *, model="base.en"):
    """Time a single-model pass on one clip."""
    from .._bench import (
        BenchResult, load_stt_model, transcribe_timed, timed, word_error_rate)
    m, load_s = timed(lambda: load_stt_model(model))
    text, tr_s = transcribe_timed(m, audio)
    return BenchResult(
        method="continuous",
        model_load_s=round(load_s, 3),
        transcribe_s=round(tr_s, 3),
        audio_s=round(len(audio) / sr, 3),
        text=text,
        wer=word_error_rate(ref, text) if ref else None,
    )
