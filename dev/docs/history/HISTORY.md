# JROS — development history

Release-by-release summary. Detailed per-release notes live in
[`revision_summaries/`](../revision_summaries/); the active roadmaps + design docs
live under each area folder (see [README.md](../README.md)). The repo-root
`CHANGELOG.md` tracks the in-progress release in detail.

## 0.1.0 — initial framework
The agent core: the loop, persistent memory, the skill system, the kanban
board, and the first verification benchmark.
→ [revision_summaries/0.1.0.md](../revision_summaries/0.1.0.md)

## 0.2.0 — daemon + unified surfaces
Daemon architecture; one agent behind CLI / TUI / GUI surfaces.
→ [revision_summaries/0.2.0.md](../revision_summaries/0.2.0.md) · [ROADMAP_0.2.0.md](ROADMAP_0.2.0.md)

## 0.3.0 — review-driven consolidation
Consolidation off the Odysseus review + game plan.
→ [revision_summaries/0.3.0.md](../revision_summaries/0.3.0.md) · [odysseus_review_and_0.3.0_plan.md](odysseus_review_and_0.3.0_plan.md)

## 0.4.0 — embodied node architecture
The transport bus + nodes (audio / STT / TTS / animation / motor / light /
vision), the realtime audio node, and voice-gate unification.
→ [revision_summaries/0.4.0.md](../revision_summaries/0.4.0.md) · [ROADMAP_0.4.md](ROADMAP_0.4.md) · [audio/](../audio/)

## 0.5.0 — animation · personality · skill tree (current)
The animation/avatar pipeline, the character/persona system, the XP skill
tree, and the app/windowed framework. This cycle also delivered: pipeline
tracing, the Mochi → JROS GUI + node migration (Jaeger Studio, `media` +
`animation_dev` nodes), the swappable STT method layer + bench, functional
Studio tabs, and the media-node fix.
→ [ROADMAP_0.5.md](ROADMAP_0.5.md) · `CHANGELOG.md` (repo root) · [../../infographic/](../../infographic/)

## Next — 0.6 / 0.7
The JP01 hardware adapter layer: mic-in / RGB-out / speaker-out streaming
adapters on the device, riding the `MediaFrame` / `ZmqBus` seam declared in
0.5.0.
→ [hardware/](../hardware/) · [hardware/JROS_HARDWARE_FRAMEWORK_PLAN.md](../hardware/JROS_HARDWARE_FRAMEWORK_PLAN.md)
