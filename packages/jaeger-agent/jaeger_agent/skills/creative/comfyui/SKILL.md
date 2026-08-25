---
name: comfyui
description: "Install, operate, or automate ComfyUI workflows for image, video, or audio generation. Use when the user explicitly names ComfyUI or supplies a ComfyUI workflow JSON."
license: MIT
compatibility: Requires local/desktop/cloud ComfyUI; local generation depends on suitable GPU, RAM, and disk.
metadata:
  jros:
    version: 6.0.0
    lifecycle: optional
    skill-class: first-class
    platforms: [macos, linux, windows]
    requires-tools: [terminal]
    tags: [comfyui, image-generation, video-generation, workflow]
    category: creative
---

# COMFYUI

Use bundled scripts instead of recreating REST/WebSocket clients.

## SOP

1. Run `scripts/hardware_check.py` and choose local, Desktop, or Cloud.
2. Run `scripts/check_deps.py`; use `scripts/comfyui_setup.sh` only after the
   user accepts downloads and local resource use.
3. Select an existing workflow under `workflows/` or inspect a supplied JSON
   with `scripts/extract_schema.py`.
4. Read `references/imported-guide.md` only for the chosen setup/model/workflow.
5. Execute with `scripts/run_workflow.py`; use `scripts/ws_monitor.py` only when
   live progress is needed.
6. Verify returned output files and preserve the exact workflow/seed/settings.

## ERROR HATCH

- Missing model or custom node: report its exact name; do not recursively install
  arbitrary dependencies without approval.
- Server unreachable: run the health check once, then stop with its diagnostics.

## DONE WHEN

The workflow completed, output files exist, and the endpoint, workflow, seed,
and material parameter overrides are reported.
