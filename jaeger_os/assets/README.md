# assets/

**Static media that ships with the framework.** Small, framework-zone,
committed to git. Logos, banners, sample audio used in docs, fixture
images for plugin smoke tests, demo files referenced from examples.

| Goes here | Does NOT go here |
|---|---|
| logos, banners, screenshots | LLM weights (`*.gguf`) — external cache |
| demo audio clips for docs | Whisper weights — declared in `plugins/whisper_stt/plugin.yaml` |
| fixture images for tests | Kokoro voice files — inside `plugins/kokoro_tts/voices/` |
| sample CSV / JSON for demos | NN-trained skill weights — inside `<instance>/skills/<name>_vN/weights/` |
| README screenshots | per-instance state (logs, memory, credentials) — `<instance>/` |

**Size rule of thumb:** if a file is larger than ~10 MB and not load-bearing
for understanding the docs, it belongs somewhere else. See
[docs/VOCABULARY.md → Where models and assets live on disk](../../docs/VOCABULARY.md)
for the full convention.

Convention borrowed from `python_hermes_agent/upstream/assets/`.
