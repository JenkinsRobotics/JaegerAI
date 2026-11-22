# droid — the Mac Studio as Jaeger's body

Droid mode turns the Mac into an embodied Jaeger: the Insta360 Link 2 is its
eyes and ears (its gimbal is its neck), the Mac Studio's speakers are its
voice, and the Mac itself is its hands. You wake it from the Stream Deck and talk; no
keyboard, mouse or monitor is assumed. It is still one Jaeger: every
utterance is a normal Gateway turn on the home chat (`agent-native:jaeger`),
with the same memory, tools, Autonomy reviewer and approvals.

```text
Stream Deck WAKE DROID ─► runner (curl) ─┐
Jaeger menu bar (Droid section) ─────────┼─► ~/.jaeger/run/droid/control.sock
                                         │
Jaeger Droid.app (headless; holds mic/camera permission)
  └─ python -m jaeger_ai.features.droid.service   (voice venv)
       ├─ AVAudioEngine + Apple voice processing (echo cancel) ─ mic / speakers
       ├─ WebRTC client of the realtime voice service :8794
       │     Silero VAD → Parakeet STT → Smart Turn → … → Phonon TTS
       └─ Gateway turns on the home chat (fast voice lane; work → full Jaeger)
```

## Behaviour

* **Wake** (deck key, Jaeger menu bar Droid section, `POST /wake`): rising chime,
  then a spoken greeting. Speech plays on `droid.json` `speaker` (default *Mac
  Studio Speakers*) by binding the audio engine to that device, so a leftover
  virtual output such as Jump Desktop Audio can stay the system default. If
  that speaker is missing or the engine cannot start on it, the droid falls
  back to another real output and the menu status explains the switch.
* **Talk**: Smart Turn decides when you're done; replies are spoken sentence by
  sentence as they stream. Talking over the droid pauses the current speech
  unit (echo cancellation comes from the shared voice-processing engine).
  A short backchannel such as "yeah" resumes the unfinished thought; a
  correction or question abandons unheard speech, steers the active Gateway
  turn, and speaks the revised continuation. Emergency stop phrases still
  halt immediately. The delivered-speech ledger distinguishes queued,
  interrupted and actually played speech. Long answers are capped
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

## Eyes, neck and hands (steps 3–5)

* **Eyes**: while awake the service opens the camera (`droid.json` `camera`,
  default *Insta360 Link 2*) at 1280x720. Frames stay on the Mac: questions
  such as "what do you see?", "what am I holding?", "how do I look?" are
  answered by the local vision model (Ollama `qwen3-vl:8b-instruct`, ~1.5 s
  warm) and never by a cloud model. It describes people, never names them.
* **Presence**: OpenCV face detection every 1.5 s. When someone appears after
  more than `presence_greet_after_s` (600 s) with nobody in view, the droid
  says "Ah, welcome back, Matthew." (or greets everyone when there are several).
* **Neck**: "look left / right / up / down / a bit to the left / look at me /
  look ahead" turn the Link 2 gimbal with standard UVC camera-terminal controls
  (`CT_PANTILT_ABSOLUTE`, as in Insta360's UVC SDK guide) via `bin/droid-ptz`;
  "look around (the room)" pans left, centre and right and describes all three.
  On sleep the head returns to its privacy pose (pointing down). The Insta360
  Link Controller app is not used or modified.
* **Hands**: everything else is a normal Jaeger turn, so computer use goes
  through Jaeger's own computer tools (CuaDriver). The droid narrates what it
  is doing ("Opening Safari.", "Let me look at the screen.", "Typing that in.")
  at most once every 6 s and 5 times per turn. Destructive or outward actions
  still hit the Autonomy reviewer and are confirmed out loud.
* **Headless**: `GET /display` reports whether the screen is real or virtual.
  `bin/droid-display` creates a 1920x1080 virtual display only when no display
  at all is online, so computer use still has a screen with no monitor.
* **Live view**: Machine › Droid in the WebUI (`/machine?section=droid`, also
  the Jaeger menu's *Open Droid View*) shows the screen, the camera, the running
  transcript and Wake / Mute / Look around / Stop.
* **Stream Deck**: WAKE DROID (toggle), LOOK (look around), STOP (stop
  talking), MUTE (microphone). LOOK and STOP replace the old VIDEO CHAT and
  STOP CHAT keys; their applets were moved to `~/Desktop/Jaeger-removed-*`.

## Files

| File | Role |
| :--- | :--- |
| `service.py` | resident service, state machine, control socket, turns, approvals |
| `audio.py` | one AVAudioEngine: voice-processed mic tap + player node, chimes |
| `coreaudio.py` | list devices; read/set the default output (ctypes) |
| `persona.py` | droid framing, greetings, spoken commands, yes/no, head moves, narration |
| `vision.py` | camera capture, presence, local vision model, gimbal head |
| `native/droid-ptz.m` | UVC pan/tilt/zoom for the Insta360 Link gimbal (IOKit) |
| `native/droid-display.m` | virtual display when the Mac is truly headless |
| `native/DroidHost.swift` | headless host app; permissions; keeps the service alive |
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

`GET /status`, `/transcript`, `/display`, `/camera.jpg`, `/screen.jpg`;
`POST /wake` (`{"ears": false}` = speaker-only diagnostics), `/sleep`,
`/toggle`, `/mute`, `/stop`, `/say {"text"}`, `/look {"question", "around"}`,
`/hear {"text"}`. The WebUI forwards all but `/hear` at `/api/jaeger/droid/*`.

## Honest limits

* macOS asks once for Microphone (and Camera) for *Jaeger Droid*; until then
  waking reports the missing permission instead of listening.
* The Insta360 Link 2 is a 4K gimbal webcam (flat UVC image, pan/tilt), not
  an equirectangular 360 camera; "looking around" is the gimbal panning.
* The gimbal moves only while the camera is streaming (i.e. while awake).
* The screen in the live view comes from CuaDriver, which already holds
  Screen Recording, so Jaeger Droid itself needs only Microphone and Camera.

## Living heartbeat (Droid Life)

Modes: **off** (night, or "go to sleep" / "power down": camera and mic closed until the next 9 AM or an
explicit wake), **present** (active hours, `droid.json` `active_hours`, default 9-23: Apple Vision person/face/
head-pose detection at 2-5 fps plus a Silero VAD on the mic; nothing is recorded or transcribed, the voice
service receives silence) and **conversation** (the existing voice loop). "That's all" or 2 minutes without
speech returns to present; Stream Deck toggle goes present -> conversation -> off.

* `life.py`: blackboard, reflexes (graded head turns toward people and sound, glances, look-around when
  alone), drives (social, curiosity, energy, confidence; `~/.jaeger/droid/drives.json`), the speak-or-quiet
  `Gate` (active hours, quiet mode, present and facing, guests -> no private content, not mid-conversation,
  max 1 unprompted line per 15 min and 4 per hour, small talk max 2/day with backoff when ignored).
* Halts: Stream Deck STOP (2 min), "quiet" (1 h, "you can talk again" ends it), Matthew starting to speak.
* Logs (derived text only, 7 days, deletable in the Droid view): `~/.jaeger/droid/noticed.jsonl` and
  `decisions.jsonl`.
* Identity: face (YuNet + SFace) and voice (WeSpeaker ResNet34) embeddings in `~/.jaeger/droid/identity/`
  (0600), learned and deleted from the Droid view. Models in `~/.jaeger/droid/models/`.
* Gateway: `deliver_proactive` offers each unprompted line to `POST /proactive`; `speak` plays it in the
  room (the apps don't repeat it), `push` sends a Web Push (`proactive_away`).
* Reflection is event-driven (`core/runtime/reflection_triggers.py`): arrival, return after 30+ min, job
  finished, approval waiting. `JAEGER_HEARTBEAT_TIMER=1` restores the 30-minute timer.
