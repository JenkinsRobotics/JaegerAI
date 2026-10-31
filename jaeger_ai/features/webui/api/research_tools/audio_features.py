"""Audio features with librosa. Usage: audio_features.py <audio.wav> <out.json> — runs in .venv-research.
Per-second RMS loudness (dBFS), tempo + beat times, onset rate, spectral centroid, and a rough
speech/music split (percussive/harmonic energy + beat strength). No model calls."""
import json, sys
import numpy as np
import librosa

y, sr = librosa.load(sys.argv[1], sr=22050, mono=True)
dur = len(y) / sr
hop = 512
rms = librosa.feature.rms(y=y, hop_length=hop)[0]
fps = sr / hop
per_s = [float(20 * np.log10(max(np.mean(rms[int(i * fps):int((i + 1) * fps)] or [1e-6]), 1e-6))) for i in range(int(dur))]
onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, hop_length=hop)
onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, hop_length=hop, units="time")
cent = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop)[0]
h, p = librosa.effects.hpss(y)
beat_strength = float(np.mean(onset_env[beats])) / (float(np.mean(onset_env)) + 1e-9) if len(beats) else 0.0
out = {
    "duration_s": round(dur, 2), "sample_rate": sr,
    "loudness_dbfs_per_s": [round(v, 1) for v in per_s],
    "loudness_dbfs_mean": round(float(np.mean(per_s)) if per_s else 0, 1),
    "loudness_dbfs_p10_p90": [round(float(np.percentile(per_s, 10)), 1), round(float(np.percentile(per_s, 90)), 1)] if per_s else None,
    "tempo_bpm": round(float(np.atleast_1d(tempo)[0]), 1), "beat_times_s": [round(float(t), 2) for t in librosa.frames_to_time(beats, sr=sr, hop_length=hop)][:2000],
    "beat_strength_ratio": round(beat_strength, 2),
    "onsets_per_min": round(len(onsets) / (dur / 60), 1) if dur else None,
    "spectral_centroid_hz_mean": round(float(np.mean(cent)), 0),
    "harmonic_percussive_ratio": round(float(np.sum(h ** 2) / (np.sum(p ** 2) + 1e-9)), 2),
    "music_likely": bool(beat_strength > 1.6),
    "note": "music_likely is a heuristic (steady beat strength), not a classifier",
}
open(sys.argv[2], "w").write(json.dumps(out))
print(json.dumps({k: out[k] for k in ("duration_s", "tempo_bpm", "loudness_dbfs_mean", "music_likely")}))
