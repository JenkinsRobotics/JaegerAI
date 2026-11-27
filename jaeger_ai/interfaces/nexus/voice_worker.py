"""Jaeger AI's voice and hearing for the NexusUI avatar: Jaeger Agent's own SpeechRuntime (the Kokoro and Whisper
modules it loads and verifies), run as a worker so the app's Python needs none of it.

Run by voice.py with the Python that has Jaeger Agent 1.2.0, jaeger-kokoro-tts 0.14.0 and jaeger-whisper-stt
(JAEGER_VOICE_PYTHON). It imports nothing from jaeger_ai. One JSON line each way:

    in:  {"op": "say", "id": 1, "text": "Hello [laugh]"}   ->  {"id": 1, "rate": 24000, "pcm": <b64 int16>, "marks": [...], "ms": 210}
         {"op": "hear", "id": 2, "pcm": <b64 int16 16 kHz>}   ->  {"id": 2, "text": "what time is it", "ms": 380}
    out first: {"ready": true, "report": {"voice": {...}, "hearing": {...}}}  or  {"ready": false, "why": "..."}
"""
import base64
import json
import os
import sys
import time


def main():
    wire = os.fdopen(os.dup(1), 'w')          # the app's pipe; anything the modules print goes to the log instead
    os.dup2(2, 1); sys.stdout = sys.stderr
    emit = lambda d: (wire.write(json.dumps(d, default=str) + '\n'), wire.flush())
    try:
        import numpy as np
        from jaeger_agent.core.config import MultimodalConfig
        from jaeger_agent.core.speech import SpeechRuntime
        rt = SpeechRuntime(MultimodalConfig(kokoro_voice=os.environ.get('JAEGER_VOICE', 'af_heart'),
                                            stt_model=os.environ.get('JAEGER_HEARING', 'large-v3-turbo')))
        rt.load(lambda m: print(m, file=sys.stderr))
        emit({'ready': True, 'report': rt.status()})
    except Exception as exc:  # noqa: BLE001 — the app shows why and goes on without a voice
        emit({'ready': False, 'why': f'{type(exc).__name__}: {exc}'})
        return
    for line in sys.stdin:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        began, rid = time.time(), r.get('id')
        try:
            if r.get('op') == 'say':
                rate, parts, marks, at = rt.tts.sample_rate, [], [], 0
                for part in rt.tts.synth(str(r.get('text', ''))):   # SpeechChunks: sound plus lip marks ([laugh] plays her recorded laugh)
                    marks += [[round(a + at / rate, 3), round(b + at / rate, 3), k] for a, b, k in getattr(part, 'marks', [])]
                    parts.append(np.asarray(part, dtype=np.float32).reshape(-1)); at += len(parts[-1])
                pcm = (np.clip(np.concatenate(parts) if parts else np.zeros(0, np.float32), -1, 1) * 32767).astype('<i2').tobytes()
                emit({'id': rid, 'rate': rate, 'pcm': base64.b64encode(pcm).decode(), 'marks': marks, 'ms': round((time.time() - began) * 1000)})
            elif r.get('op') == 'hear':
                pcm = np.frombuffer(base64.b64decode(r.get('pcm', '')), dtype='<i2').astype(np.float32) / 32768
                emit({'id': rid, 'text': rt.transcribe(pcm, sample_rate=16000).strip(), 'ms': round((time.time() - began) * 1000)})
            else:
                emit({'id': rid, 'error': f"unknown op {r.get('op')!r}"})
        except Exception as exc:  # noqa: BLE001 — one bad line must not stop her voice
            emit({'id': rid, 'error': f'{type(exc).__name__}: {exc}'})


if __name__ == '__main__':
    main()
