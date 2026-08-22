"""local_agreement — LocalAgreement streaming STT (stub). See pipeline.py."""

from .pipeline import WhisperSTTLocalAgreement

__all__ = ["WhisperSTTLocalAgreement", "bench", "AVAILABLE"]

AVAILABLE = False


def bench(audio, sr, ref=None):
    from .._bench import BenchResult
    return BenchResult(
        method="local_agreement", model_load_s=0.0, transcribe_s=0.0,
        audio_s=round(len(audio) / sr, 3), text="",
        error="not implemented (stub)")
