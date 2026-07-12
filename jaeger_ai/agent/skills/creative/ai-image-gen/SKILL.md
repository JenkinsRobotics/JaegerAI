---
name: ai-image-gen
description: "Generate AI images or short video clips from text prompts — routes between the local image_generate (SDXL-Turbo, free, offline) and the fal.ai cloud tools generate_image_fal / generate_video_fal (paid, higher quality, needs FAL_KEY). Load this when the user asks for a picture, artwork, illustration, or a short generated video."
version: 1.0.0
platforms: [macos, linux, windows]
requires_tools: [image_generate, generate_image_fal, generate_video_fal, set_credential]
metadata:
  jros:
    tags: [image, video, generation, fal, flux, sdxl, ai-art, text-to-image, text-to-video]
    category: creative
    related_skills: [comfyui, pixel-art]
---

# AI IMAGE + VIDEO GENERATION

Three tools, one decision. All outputs land under the skills workspace and
the tool returns the file path — report that path to the user.

## DECISION FLOW (pick one, then call it)

1. VIDEO requested → generate_video_fal. It is the only video backend.
2. IMAGE, user wants quality / photorealism / text-in-image, or asks for
   "the good one" / a specific cloud model → generate_image_fal.
3. IMAGE, anything else (drafts, offline, no API key, cost-sensitive) →
   image_generate (local SDXL-Turbo, free, no key needed).
4. Cloud tool returns a "not configured" error → CREDENTIAL SETUP below.

## PHASE 1 — GENERATE

Local (free, offline, 1-3s after first model download):

    image_generate(prompt="a red fox in snow, golden hour",
                   out_path="fox.png")

Cloud image (paid, needs FAL_KEY, ~10-60s):

    generate_image_fal(prompt="a red fox in snow, golden hour",
                       model="flux/schnell", output_path="fox.png")

    model options: "flux/schnell" (default, fast + cheap),
    "flux/dev" (higher quality), "flux-pro/v1.1" (best).

Cloud video (paid, needs FAL_KEY, 1-5 min — tell the user it takes a while):

    generate_video_fal(prompt="a red fox trotting through snowfall",
                       output_path="fox.mp4")

    model="" uses Pixverse v6 (cheap). Premium: model="veo3.1" or
    model="kling-video/v3/4k/text-to-video".

Prompt tips: describe subject + style + lighting in one sentence. Do not
ask the user to refine the prompt first — generate, show, then iterate.

## PHASE 2 — VERIFY + REPORT

Every tool returns a dict. Success: ok/generated true with "path" and
"absolute_path". Report the path. Failure: ok false with "error" — read it,
it says what to do next.

## ERROR HATCHES

- CREDENTIAL SETUP: a fal tool returns "fal.ai is not configured" →
  ask the user for their fal.ai API key (https://fal.ai/dashboard/keys),
  then set_credential("FAL_KEY", "<key>") and retry ONCE. If the user has
  no key and wants an image, fall back to image_generate.
- Key rejected (HTTP 401/403 in the error) → the stored key is wrong;
  ask the user for a fresh one. Do not retry with the same key.
- fal tool times out or fails twice → fall back to image_generate for
  images; for video, report the error — there is no local fallback.
- image_generate errors (e.g. weights not downloadable) → offer
  generate_image_fal as the alternative.

## DONE WHEN

The returned "path" exists in the workspace and you have told the user
that path (plus the model used). One generation per request unless the
user asks for variations.
