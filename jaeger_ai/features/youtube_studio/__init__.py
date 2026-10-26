"""YouTube studio — a configurable video content pipeline.

Three standalone steps, each a thin layer over a tool the repo already ships:

* :mod:`.script`   brief + build logs -> episode outline/script/shot list (markdown),
                   written by the instance's configured model over Ollama's
                   OpenAI-compatible API.
* :mod:`.voice`    script markdown -> narration WAV with Kokoro (host + robot voices).
* :mod:`.roughcut` build footage -> silences trimmed with ffmpeg ``silencedetect``,
                   transcribed with the offline Whisper module, captions as SRT
                   plus a soft subtitle track in the MP4.

Channel configuration (name, host description, privacy rules) is loaded from
``~/.jaeger/instances/<name>/youtube.toml`` — see :mod:`.channel_config`.

Nothing here uploads, publishes, or touches an account. The operator films,
approves the script, and presses publish themselves.
"""
