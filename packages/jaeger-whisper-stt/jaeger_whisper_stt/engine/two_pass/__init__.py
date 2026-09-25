"""two_pass — "dual whisper": a fast ``base.en`` gates an accurate
``medium.en``, both via pywhispercpp.  The live adapter is in
``pipeline.py``; ``bench()`` is the file-driven perf probe the CLI calls.

``WhisperSTTTwoPass(accurate_model_name=None)`` is the single-pass
``vad_segment`` method — same VAD worker, one model.  See the registry.
"""

from .pipeline import WhisperSTTTwoPass

__all__ = ["WhisperSTTTwoPass", "bench", "bench_vad_segment"]


def bench(audio, sr, ref=None, *, fast="base.en", accurate="medium.en"):
    """Time the two-model cascade on one clip (fast pass + accurate pass)."""
    from .._bench import (
        BenchResult, load_stt_model, transcribe_timed, timed, word_error_rate)
    fast_m, load_fast = timed(lambda: load_stt_model(fast))
    acc_m, load_acc = timed(lambda: load_stt_model(accurate))
    fast_text, fast_s = transcribe_timed(fast_m, audio)
    acc_text, acc_s = transcribe_timed(acc_m, audio)
    return BenchResult(
        method="two_pass",
        model_load_s=round(load_fast + load_acc, 3),
        transcribe_s=round(fast_s + acc_s, 3),
        audio_s=round(len(audio) / sr, 3),
        text=acc_text,
        extra={"fast_s": round(fast_s, 3), "accurate_s": round(acc_s, 3),
               "fast_text": fast_text},
        wer=word_error_rate(ref, acc_text) if ref else None,
    )


def bench_vad_segment(audio, sr, ref=None, *, model="base.en"):
    """Single-pass probe — one model, committed straight from the VAD
    segment.  The point of running it next to ``two_pass`` is to see
    what the accurate pass actually buys you in WER for its extra
    seconds."""
    from .._bench import (
        BenchResult, load_stt_model, transcribe_timed, timed, word_error_rate)
    m, load_s = timed(lambda: load_stt_model(model))
    text, tr_s = transcribe_timed(m, audio)
    return BenchResult(
        method="vad_segment",
        model_load_s=round(load_s, 3),
        transcribe_s=round(tr_s, 3),
        audio_s=round(len(audio) / sr, 3),
        text=text,
        wer=word_error_rate(ref, text) if ref else None,
    )
