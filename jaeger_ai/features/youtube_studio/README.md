# youtube_studio — scripted content generation & audio assembly

```text
research notes → script generation → TTS narration synthesis
               → roughcut assembly → transcript alignment
```

The YouTube Studio feature provides automated narration script drafting,
voice audio generation (via Kokoro-82M TTS), and roughcut audio-clip alignment
for YouTube content workflows.

Switch it off by not invoking `jaeger channel`; nothing else in core depends on this folder.

## CLI Commands

```bash
jaeger channel script <topic>       # generate structured video narration script
jaeger channel voice <script.json>  # synthesize voiceover audio clips
jaeger channel roughcut <dir>       # assemble and align voice clips with rough timings
```

## Structure

| File | Purpose |
| :--- | :--- |
| `script.py` | Topic outline, hook generation, script segmentation, and timing estimates |
| `voice.py` | Batch text-to-speech rendering and narration segment audio files |
| `roughcut.py` | Clip concatenator, silence trim, pacing, and subtitle track generation |
| `__init__.py` | Feature export symbols and public API |

## Testing

Verified by `dev/tests/jaeger_ai/features/youtube_studio/`:
- `test_script.py`
- `test_voice.py`
- `test_roughcut.py`
