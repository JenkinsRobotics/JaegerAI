"""window — rolling-window captions, no phrase segmentation.

Precursor: MockingAgent ``PywisperCpp/pywhispercpp_examples/livestream_mic.py``.
The live adapter is in ``pipeline.py``; ``bench()`` is the perf probe.

``WhisperSTTWindow`` also backs ``local_agreement`` (same machine, different
commit rule) — see ``pipeline.py``'s module docstring.
"""

from .pipeline import (
    WhisperSTTWindow,
    agreed_prefix_len,
    commit_cursor,
    word_pairs,
)

__all__ = ["WhisperSTTWindow", "commit_cursor", "agreed_prefix_len",
           "word_pairs", "bench"]


def bench(audio, sr, ref=None, *, model="base.en", window_s=7.0):
    """Time the rolling-window strategy: decode the LAST ``window_s`` of
    the clip, which is the unit of work this mode repeats live.  RTF is
    reported against that window, not the whole clip, so it answers the
    question that matters — can one pass finish before the next is due?
    """
    from .._bench import (
        BenchResult, load_stt_model, timed, transcribe_timed, word_error_rate)
    m, load_s = timed(lambda: load_stt_model(model))
    tail = audio[-int(window_s * sr):] if len(audio) > window_s * sr else audio
    text, tr_s = transcribe_timed(m, tail)
    return BenchResult(
        method="window",
        model_load_s=round(load_s, 3),
        transcribe_s=round(tr_s, 3),
        audio_s=round(len(tail) / sr, 3),
        text=text,
        extra={"window_s": round(len(tail) / sr, 3)},
        # WER only means something when the window covered the whole
        # clip; a tail decode has nothing to compare a full ref against.
        wer=word_error_rate(ref, text) if ref and len(tail) == len(audio) else None,
    )
