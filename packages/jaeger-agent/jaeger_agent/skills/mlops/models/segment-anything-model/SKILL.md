---
name: segment-anything-model
description: "Segment objects in images with Meta SAM using point, box, or automatic-mask prompts. Use for explicit zero-shot segmentation, annotation assistance, or mask-generation workflows."
license: MIT
compatibility: Requires Python, PyTorch, SAM/Transformers, a checkpoint, and sufficient memory.
metadata:
  jros:
    version: 2.0.0
    lifecycle: optional
    skill-class: first-class
    platforms: [linux, macos, windows]
    requires-tools: [execute_code, terminal]
    tags: [sam, segmentation, computer-vision, masks]
    category: mlops
---

# SEGMENT ANYTHING

## SOP

1. Resolve input image, desired objects, prompt type, output mask format, and
   accuracy/performance constraints.
2. Verify installed implementation and checkpoint path before downloading.
3. Choose the smallest suitable model and record device/checkpoint/version.
4. Read `references/imported-guide.md` only for the chosen API and prompt mode.
5. Run one image first; validate mask dimensions, coordinates, and overlay.
6. Save masks and a visual overlay before any batch run.

## ERROR HATCH

- Coordinate/shape mismatch: stop and inspect image orientation and transformed
  dimensions; never stretch a mask silently.
- Missing memory/checkpoint: report the exact requirement and offer a smaller model.

## DONE WHEN

Masks align with the source image, output files exist, and model/checkpoint,
prompt coordinates, and confidence/selection policy are reported.
