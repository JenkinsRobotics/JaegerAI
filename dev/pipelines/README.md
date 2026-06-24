# dev/pipelines — human-runnable pipeline probes

One script per pipeline. Each boots **just that pipeline**, drives it, and
prints what happened — so you (or a second dev) can check each piece in
isolation. The automated pytest suite lives in `dev/tests/`; these are the
**manual** probes.

Run with the repo's venv (the deps live there):

```
.venv/bin/python dev/pipelines/<probe>.py [args]
```

| Probe | Pipeline | What it does | Needs |
|---|---|---|---|
| `stt.py` | Voice in · ASR | bench the STT methods on a WAV | a clip + whisper models |
| `tts.py` | Voice out · TTS | speak a phrase through the Kokoro TTS node | Kokoro |
| `avatar.py` | 2D avatar | boot the animation node + trigger an expression | — |
| `media.py` | Media | boot the media node (surfaces its missing topics) | — |
| `tracing.py` | Observability | emit trace steps + print the baseline | — |
| `nodes.py` | Node harness | boot an isolated echo node + drive it | — |
| `gui.py` | Surfaces | launch the dev surface gallery (Studio / players) | a display |

Status crib (full map in `docs/infographic/`): STT / TTS / 2D avatar = built;
the media node's bus topics are undefined; 3D avatar + `local_agreement` STT =
planned.
