"""LocalAgreement streaming STT and a real growing-window benchmark."""
from .pipeline import WhisperSTTLocalAgreement, agreed_prefix

__all__ = ["WhisperSTTLocalAgreement", "bench", "AVAILABLE"]
AVAILABLE = True


def bench(audio, sr, ref=None, *, model="base.en"):
    """Measure consecutive growing-window decodes plus the final transcript."""
    from .._bench import BenchResult, load_stt_model, transcribe_timed, timed, word_error_rate

    if sr <= 0:
        raise ValueError("sample rate must be positive")
    engine, load_s = timed(lambda: load_stt_model(model))
    previous = ""
    text = ""
    elapsed = 0.0
    partials = []
    step = max(1, int(sr * 0.6))
    for end in [*range(step, len(audio), step), len(audio)]:
        if not end:
            continue
        text, duration = transcribe_timed(engine, audio[:end])
        elapsed += duration
        stable = agreed_prefix(previous, text)
        if stable and (not partials or stable != partials[-1]):
            partials.append(stable)
        previous = text
    return BenchResult(
        method="local_agreement", model_load_s=round(load_s, 3),
        transcribe_s=round(elapsed, 3), audio_s=round(len(audio) / sr, 3),
        text=text, extra={"partials": partials}, wer=word_error_rate(ref, text) if ref else None,
    )
