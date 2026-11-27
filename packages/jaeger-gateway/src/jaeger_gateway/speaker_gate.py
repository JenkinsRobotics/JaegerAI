"""Local speaker verification against a deliberately enrolled voice sample."""
from functools import lru_cache
import os
from pathlib import Path
import tempfile
import wave


@lru_cache(maxsize=1)
def _encoder():
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    return ort.InferenceSession(str(Path.home() / ".cache/jaeger/models/wespeaker.onnx"),
                                sess_options=options, providers=["CPUExecutionProvider"])


def verify_voice(wav: Path, enroll: bool) -> str:
    import kaldi_native_fbank as kaldi
    import numpy as np

    profile = Path(os.getenv("JAEGER_STATE_DIR") or Path.home() / ".jaeger") / "droid-speaker.npy"
    if not enroll and not profile.exists():
        return "Enroll your voice first."
    with wave.open(str(wav)) as source:
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32)
    if len(samples) < (3 if enroll else 0.8) * 16000 or np.std(samples) < 80:
        return "Need a longer, clearer voice sample."
    opts = kaldi.FbankOptions()
    opts.frame_opts.dither = 0
    opts.frame_opts.window_type = "hamming"
    opts.mel_opts.num_bins = 80
    extractor = kaldi.OnlineFbank(opts)
    extractor.accept_waveform(16000, samples.tolist())
    features = np.stack([extractor.get_frame(i) for i in range(extractor.num_frames_ready)])
    def embed(chunk):
        vector = _encoder().run(None, {"input_features": (chunk - chunk.mean(axis=0))[None, :, :]})[0].ravel()
        return vector / max(np.linalg.norm(vector), 1e-9)
    if enroll:
        with tempfile.NamedTemporaryFile(dir=profile.parent, delete=False) as out:
            np.save(out, embed(features), allow_pickle=False)
        os.replace(out.name, profile)
        return "Voice enrolled locally."
    owner = np.load(profile, allow_pickle=False)
    starts = list(range(0, max(1, len(features) - 199), 100))
    starts.append(max(0, len(features) - 200))
    for start in set(starts):
        if float(embed(features[start:start + 200]) @ owner) < 0.65:
            return "Background or uncertain speaker. Clip held locally."
    return ""
