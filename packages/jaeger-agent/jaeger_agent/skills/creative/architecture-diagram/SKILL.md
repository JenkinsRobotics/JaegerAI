---
name: architecture-diagram
description: "Create a dark-themed SVG architecture, cloud, or infrastructure diagram as HTML. Use when the user asks to visualize system components, services, networks, dependencies, or data flow."
metadata:
  jros:
    version: 2.0.0
    lifecycle: core
    skill-class: first-class
    platforms: [linux, macos, windows]
    requires-tools: [write_file, read_file, browser]
    tags: [architecture, diagram, svg, infrastructure]
    category: creative
---

# ARCHITECTURE DIAGRAM

## SOP

1. Extract components, trust boundaries, ownership, protocols, and flow direction.
2. Pick one structure: layered, left-to-right flow, hub/spoke, deployment, or
   sequence. Do not invent infrastructure absent from the source.
3. Start from `templates/template.html`; use semantic labels and a small legend.
4. Read `references/legacy-guide.md` only for detailed SVG/layout conventions.
5. Write a self-contained HTML/SVG artifact, open it in `browser`, and inspect
   clipping, label collisions, arrows, contrast, and viewport behavior.

## ERROR HATCH

If architecture facts are incomplete, label assumptions explicitly. If the graph
is too dense, split it into overview and detail instead of shrinking text.

## DONE WHEN

The rendered diagram accurately communicates components and relationships at the
target viewport with no overlap or broken connectors.
