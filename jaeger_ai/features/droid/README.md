# droid — the Mac Studio as Jaeger's body

Droid mode turns the Mac into an embodied Jaeger: the Insta360 Link 2 is its
eyes and ears, the Mac Studio's speakers are its voice, and (next phases) the
Mac itself is its hands. You wake it from the Stream Deck and talk; no
keyboard, mouse or monitor is assumed. It is still one Jaeger: every
utterance is a normal Gateway turn on the home chat (`agent-native:jaeger`),
with the same memory, tools, Autonomy reviewer and approvals.

```text
Stream Deck WAKE DROID ─► runner (curl) ─► ~/.jaeger/run/droid/control.sock
                                              │
Jaeger Droid.app (menu bar, holds mic/camera permission)
  └─ python -m jaeger_ai.features.droid.service   (voice venv)
       ├─ AVAudioEngine + Apple voice processing (echo cancel) ─ mic / speakers
       ├─ WebRTC client of the realtime voice service :8794
       │     Silero VAD → Parakeet STT → Smart Turn → … → Phonon TTS
       └─ Gateway turns on the home chat (fast voice lane; work → full Jaeger)
```

## Behaviour

* **Wake** (deck key, menu bar, `POST /wake`): rising chime, the speaker is
  routed to `droid.json` `speaker` (default *Mac Studio Speakers*; the previous
  default output is restored on sleep), then a spoken greeting.
* **Talk**: Smart Turn decides when you're done; replies are spoken sentence by
  sentence as they stream. Talking over the droid stops it (echo cancellation
  comes from the shared voice-processing engine). Long answers are capped
  (`max_spoken_chars`) with "The rest is in the chat."
* **Persona**: a short framing line makes Jaeger a courteous, gently witty
  protocol droid (C-3PO in spirit). The chat shows only what you said.
* **Approvals** are asked out loud ("…Shall I proceed?") and resolved by a
  spoken yes / no / "yes, always". Anything else is re-asked, never assumed.
* **Local phrases**: "go to sleep" / "power down" / "that's all" → standby;
  "stop" / "never mind" → stop talking.
* **Sleep**: spoken farewell, falling chime, microphone closed.

The microphone is open only while the droid is awake. The older Stream Deck
voice chat (`features/voice/control.py`) is switched off on wake so the two
never fight over the mic.

## Files

| File | Role |
| :--- | :--- |
| `service.py` | resident service, state machine, control socket, turns, approvals |
| `audio.py` | one AVAudioEngine: voice-processed mic tap + player node, chimes |
| `coreaudio.py` | list devices; read/set the default output (ctypes) |
| `persona.py` | droid framing, greetings, spoken commands and yes/no parsing |
| `native/DroidHost.swift` | menu-bar host app; permissions; keeps the service alive |
| `scripts/install-droid.py` | build/sign the host, LaunchAgent at login, deck keys |

## Install / update

```bash
~/.jaeger/venv/bin/python scripts/install-droid.py [--install-deck]
```

Rebuilds the host only when `DroidHost.swift` changes (a rebuild makes macOS
ask for microphone/camera again); otherwise just restarts the Python service.
Config lives in `~/.jaeger/droid.json` (`speaker`, `microphone`, `engine`
`local|gemini`, `session_id`, `name`, `max_spoken_chars`, `wake_on_start`).

## Control socket

`GET /status`, `POST /wake` (`{"ears": false}` = speaker-only diagnostics),
`/sleep`, `/toggle`, `/mute`, `/stop`, `/say {"text"}`, `/hear {"text"}`.
The WebUI forwards the first seven at `/api/jaeger/droid/*`.

## Honest limits

* macOS asks once for Microphone (and Camera) for *Jaeger Droid*; until then
  waking reports the missing permission instead of listening.
* The Insta360 Link 2 is a 4K gimbal webcam (flat UVC image, pan/tilt), not
  an equirectangular 360 camera; vision and head-turning are the next phases.
