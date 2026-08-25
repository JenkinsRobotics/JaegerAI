---
name: claude-design
description: "Create a polished standalone HTML design artifact. Use for landing pages, visual prototypes, or HTML-based decks when the user wants a designed artifact rather than a design-token specification."
license: MIT
metadata:
  jros:
    version: 2.0.0
    lifecycle: optional
    skill-class: first-class
    platforms: [linux, macos, windows]
    requires-tools: [write_file, read_file, browser]
    tags: [design, html, prototype, deck]
    category: creative
    related-skills: [popular-web-designs, design-md, architecture-diagram]
---

# HTML DESIGN ARTIFACTS

## ROUTING

- Known product visual language: also load `popular-web-designs`.
- Token/spec deliverable: use `design-md` instead.
- Architecture diagram: use `architecture-diagram` instead.

## SOP

1. Identify artifact type, audience, content, dimensions, and interaction needs.
2. Inspect provided source material before selecting the visual direction.
3. Read only the relevant portion of `references/imported-guide.md` for artifact
   rules, typography, layout, motion, or anti-slop guidance.
4. Build a self-contained HTML artifact with semantic structure and accessible
   contrast, keyboard behavior, and reduced-motion handling.
5. Open it with `browser`, inspect the rendered result, and correct overflow,
   broken assets, or unusable controls.

## ERROR HATCH

If requirements are insufficient, produce one coherent direction with clearly
stated assumptions instead of blocking or generating several vague variants.

## DONE WHEN

The HTML artifact exists and has been visually verified at its target viewport.
