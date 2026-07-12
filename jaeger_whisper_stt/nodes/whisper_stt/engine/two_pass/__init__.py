"""two_pass — "dual whisper": a fast ``base.en`` gates an accurate
``medium.en``, both via pywhispercpp.  The live adapter is in
``pipeline.py``; ``bench()`` is the file-driven perf probe the CLI calls.
"""

from .pipeline import WhisperSTTTwoPass

__all__ = ["WhisperSTTTwoPass", "bench"]


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
