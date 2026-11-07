# Droid voice and video conversation

The conversation controller owns one device client, connected to the resident
Gateway and its persistent `voice-droid` session. It never creates another agent.
Audio uses the JaegerOS audio driver, Whisper and Kokoro. Answer sentences are
spoken as Gateway deltas arrive. Reasoning events are never spoken.

`python -m jaeger_ai.features.voice.control serve` starts the local control socket.
Commands `voice` and `video` toggle their mode; `off` stops either mode; `status`
reports actual worker state. Only the local user can access the socket.
The installed service starts idle; neither microphone nor camera opens on login.
Stopping terminates the device worker, including pending model work and capture.

`scripts/install-conversation-controls.py` installs a launch agent and, with
`--install-deck`, Voice Mode, Video Chat and Stop Chat keys on the existing JAEGER
Stream Deck page. Existing occupied extra keys are preserved. The installer
backs up the modified page and configuration under the operator state directory.
Supply `--input-device`, `--output-device`, `--camera-index` and
`--vision-model-path` (a trusted cached Moondream snapshot). No models download
at runtime. Configuration lives at `~/.jaeger/conversation.json`.

Video samples the camera into a local vision model continuously while enabled.
Images stay in memory. Camera descriptions are not sent to the Gateway by default.
Explicit operator consent and `share_visual_context: true` in conversation.json
allow descriptions to reach the configured conversational model and session memory. Descriptions
older than 30 seconds are withheld. This is sampled visual context, not a video
call to another person. Local vision speed determines refresh latency.

When Speex echo cancellation is available, speech can interrupt playback.
Without it, the service reports `duplex: false` and pauses recognition during
playback to prevent speaker feedback. Full duplex quality and first audible
response latency require a physical microphone/speaker conversation test.
The installer builds a small native permission host, Jaeger Conversation. macOS
camera and microphone permission prompts must be accepted on that Mac. This host
runs only the device client; identity, models and memory remain owned by Jaeger's
Gateway. Without permission, the service reports a capture error instead of
claiming to be listening or watching.
Errors and current device state are in `~/.jaeger/run/conversation/status.json`;
startup errors are also in `~/.jaeger/logs/conversation.log`.

While listening, say “open your eyes” or “look around the room” to enable the
camera, or “close your eyes” to disable it without ending voice conversation.
Without visual sharing consent, “what do you see” speaks the local model's
description directly; no camera evidence reaches the cloud or Gateway memory.
The opening turn waits up to 20 seconds for fresh evidence and reports
unavailability rather than inventing a scene. Vision prioritizes people and
observable actions, clear hazards, object positions, then uncertain room/activity
guesses. Positions are relative to the image, not measured 3D coordinates.
This cannot inspect areas outside the camera view or physically pan the camera.
Native macOS authorization status is reported in
`~/.jaeger/conversation-permissions.json`; software cannot grant itself consent.
