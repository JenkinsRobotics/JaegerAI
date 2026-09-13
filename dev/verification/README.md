# Release verification

Run from the JaegerAI repository using its Python environment.

`security_gate.py` creates sanitized temporary state and runs the full
adversarial suite under an enforced macOS sandbox. It first verifies denied
outside reads, writes, permission changes, and network connections. Failed or
inconclusive scenarios fail the command; temporary state alone is not isolation.

```sh
.venv/bin/python dev/verification/security_gate.py \
  --source-instance .jaeger_os/instances/jaeger-dev \
  --output /tmp/security-results.json
```

`multimodal_capture.py` runs the real camera and microphone through the built
app's embedded helper. It tests mute, camera toggle, resource restart, and
stable geometry. It saves counts and levels, never audio or images. See its
module docstring for invocation with the bundle's Python home and site packages.
This does not certify acoustic echo cancellation, double-talk, or speech quality.

`dev/benchmark/attached_multimodal.py` runs reference text, memory, image, and
recorded-speech cases against an isolated bridge. It uses the original scorer,
requires audio on spoken benchmark cases, and fails on wrong answers or runtime
errors. Optional `--workflow`, `--mode-switch`, and `--cancel-turn` test real file
read/write, conversation continuity, and inference cancellation with recovery.
Use `--installed-vad` to verify the packaged VAD independently of developer paths.
The benchmark requires the separate VoiceLLM case pack;
its arguments are documented by `--help`.

Builds must also pass `dev/scripts/check_wheel.py`, Swift tests, and the native
build script's signature and embedded-interpreter launch checks. Distribution
builds require a Developer ID identity; the current native launcher also needs
its source installation and Python environment, so it is not a portable app zip.
