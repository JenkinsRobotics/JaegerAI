---
name: meme-generation
description: "Generate real meme .png files — pick a classic template (drake, this-is-fine, expanding-brain, ~100 imgflip templates) and overlay captions with the bundled Pillow script, or caption a fresh AI-generated scene. Load this when the user says 'make a meme', 'meme this', or wants a joke image about a topic. For non-meme AI images use ai-image-gen instead."
version: 2.1.0
platforms: [linux, macos, windows]
requires_tools: [terminal, read_file, generate_image_fal, image_generate, vision_analyze]
metadata:
  jros:
    tags: [creative, memes, humor, images, imgflip, pillow]
    category: creative
    related_skills: [ai-image-gen, ascii-art]
---

# MEME GENERATION

Renders an actual .png: template image + caption overlay via the bundled
script at `{{skill_folder}}/scripts/generate_meme.py` (needs Pillow).

## TOOLS

- `terminal(command="python {{skill_folder}}/scripts/generate_meme.py ...")` — render the meme.
- `generate_image_fal(prompt="...")` — custom scene for Mode 2 (cloud, paid, best quality).
- `image_generate(prompt="...")` — local/offline fallback when fal.ai/FAL_KEY is unavailable.
- `vision_analyze(image_path="...", question="...")` — check the result is legible.

## CURATED TEMPLATES (hand-tuned text placement)

this-is-fine            top, bottom          chaos, denial
drake                   reject, approve      rejecting one thing, preferring another
distracted-boyfriend    distraction, current, person   temptation, shifting priorities
two-buttons             left, right, person  impossible choice
expanding-brain         4 levels             escalating irony
change-my-mind          statement            hot takes
woman-yelling-at-cat    woman, cat           arguments
one-does-not-simply     top, bottom          deceptively hard things
grus-plan               step1-3, realization plans that backfire
batman-slapping-robin   robin, batman        shutting down bad ideas

Any other imgflip template works by name or ID (smart default placement).
Search: `--search "disaster"`. List curated: `--list`.

## MODE 1 — CLASSIC TEMPLATE (default)

1. Identify the joke's core dynamic (chaos, dilemma, preference, irony...).
2. Pick the template whose structure matches the JOKE, not just the topic.
   Nothing fits? `terminal(command="python {{skill_folder}}/scripts/generate_meme.py --search '<keyword>'")`.
3. Write one short caption per field — 8-12 words MAX, shorter is better.
   Caption count must equal the template's field count.
4. Render:
   `terminal(command="python {{skill_folder}}/scripts/generate_meme.py drake out/meme.png 'Writing tests' 'Shipping to prod'")`
5. Report the output path to the user.

More worked examples: read_file("EXAMPLES.md") in this skill's folder.

## MODE 2 — CUSTOM AI SCENE (no template fits / user wants original art)

1. Write the captions FIRST.
2. Generate the scene: `generate_image_fal(prompt="<visual scene only>")` —
   describe only the scene, NO text in the prompt (the script overlays text).
   If fal.ai is unavailable (no FAL_KEY / offline), use `image_generate` instead.
   Note the returned image path.
3. Overlay captions on it:
   overlay style (white text, black outline, directly on the image):
   `terminal(command="python {{skill_folder}}/scripts/generate_meme.py --image <scene.png> out/meme.png 'top text' 'bottom text'")`
   bars style (black bars above/below — use when the image is busy):
   add `--bars` after `--image <scene.png>`.
4. Verify: `vision_analyze(image_path="out/meme.png", question="Is the meme text legible and well positioned?")`.
   If it flags problems, switch overlay/bars or regenerate the scene once.
5. Report the output path.

## RULES

- SHORT captions. Long text ruins memes and overflows the boxes.
- Template downloads cache in scripts/.cache/ — first render needs network.
- No hateful, abusive, or personally targeted content.

## ERROR HATCH

- `ModuleNotFoundError: PIL` → `terminal(command="pip install pillow")`, rerun.
- Template fetch fails twice (network/imgflip down) → fall back to Mode 2
  with a locally generated scene; don't hammer imgflip.
- `generate_image_fal` errors (missing FAL_KEY) → use `image_generate`; if
  that also fails, tell the user image generation is unavailable and stop.

## DONE WHEN

The .png exists at the output path, `vision_analyze` (or the script's clean
exit) confirms legible text, and the path is reported to the user with the
captions used.
