Migrated Mochi MScript renderer — under-development, not wired into any manifest or module.yaml today.
Its one real delta vs. `nodes/animation/`: publishes `AvatarFrame` (MScript's own frame type) instead of the shared `FrameBuffer`.
Left as-is deliberately for 0.8 M2c (no live consumers to module-ize against yet) — see `dev/docs/JROS_0.8_M2c_ANIMATION_MEDIA_PLAN.md`.
