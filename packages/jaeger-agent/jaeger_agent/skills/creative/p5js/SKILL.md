---
name: p5js
description: "Create a p5.js sketch or interactive canvas artifact. Use for explicit p5.js, generative art, particles, shaders, browser animation, or interactive data visualization requests."
metadata:
  jros:
    version: 2.0.0
    lifecycle: optional
    skill-class: first-class
    platforms: [linux, macos, windows]
    requires-tools: [write_file, terminal, list_skills]
    tags: [p5js, generative-art, canvas, shader, visualization]
    category: creative
---

# P5.JS PRODUCTION

## SOP

1. Select mode: static, animated, interactive, data-driven, audio-reactive, or
   WebGL/shader; establish canvas size and export target.
2. Choose one visual system and define a small parameter set before coding.
3. Read only the relevant mode/API/export reference in
   `references/imported-guide.md` and the focused files under `references/`.
4. Start from `templates/viewer.html`; implement deterministic seed/reset behavior
   when reproducibility matters.
5. Run the local server, inspect the sketch, and check console/performance.
6. Use bundled export scripts for frames or video rather than ad-hoc capture.

## ERROR HATCH

- WebGL/shader failure: reduce to the smallest failing shader and report console
  output; do not silently replace the requested medium.
- Export failure: keep the working interactive artifact and report the blocker.

## DONE WHEN

The sketch runs without console errors at the target size and the requested HTML
or exported media exists.
