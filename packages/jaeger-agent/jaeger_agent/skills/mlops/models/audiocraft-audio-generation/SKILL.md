---
name: audiocraft-audio-generation
description: "Generate music or sound effects with Meta AudioCraft. Use when the user explicitly requests MusicGen, AudioGen, EnCodec, melody-conditioned music, or a local AudioCraft pipeline."
license: MIT
compatibility: Requires Python, PyTorch, AudioCraft, and substantial model storage.
metadata:
  jros:
    version: 2.0.0
    lifecycle: optional
    skill-class: first-class
    platforms: [linux, macos]
    requires-tools: [execute_code, terminal]
    tags: [audio, musicgen, audiogen, music, sound]
    category: mlops
---

# AUDIOCRAFT AUDIO GENERATION

Use AudioCraft for explicit local MusicGen, AudioGen, or EnCodec work. For
songwriting alone use `songwriting-and-ai-music`; for an already configured
music service use its specialist skill.

## TOOLS

```text
terminal(command="python3 -c 'import torch, audiocraft'")
execute_code(...)  deterministic Python generation or inspection
```

## SOP

1. Confirm output type: music, sound effect, melody-conditioned music, or codec.
2. Check Python imports and available device before downloading a model.
3. Read `references/imported-guide.md` only for the selected model/workflow.
4. Choose the smallest model that meets quality needs and disclose downloads.
5. Generate one bounded sample, save it to the requested workspace path, and
   inspect duration/sample rate before scaling or batching.

## ERROR HATCH

- Missing package/model or insufficient memory: report the exact dependency or
  resource constraint; do not repeatedly download larger checkpoints.
- MPS/CUDA failure: use CPU only if the user accepts the slower run.

## DONE WHEN

The requested audio file exists, opens successfully, and its path, duration,
model, and generation settings are reported.
