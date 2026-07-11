# Eye / state animations (declarative JSON)

## What it is

A small JSON file describing a few keyframes — eye shape, blink
timing, position offsets — that the renderer interprets to draw
the animation.  Declarative: you write what it IS, not the
rendered pixels.

## History

- **Adobe Flash** (1996) — declarative keyframe + tween animation
  becomes mainstream
- **Lottie** (2017) — Airbnb's open-source format for After
  Effects exports.  Same idea, JSON instead of SWF
- **Rive** (2020) — modern descendant: declarative animation
  files renderable on any platform
- Mochi's `animations/*.json` is a deliberately simpler version
  of the same idea: keyframe data + a renderer that interprets it

## How it works

The JSON declares shape parameters per keyframe.  At time T, the
renderer:

1. Finds the two keyframes T sits between
2. Interpolates their parameters (eye height, x offset, ...)
3. Draws the eye shape with the interpolated values

No bitmap is stored.  No code is run beyond simple drawing.  This
is animation as DATA, not as PROGRAM and not as IMAGE.

## How Mochi implements it

- `nodes/animation/animations/__init__.py` registers
  `.json` files in `assets/animations/` as the `animations` type
- 6 entries today: `closed`, `happy_blink`, `look_down`, `look_up`,
  `neutral_blink`, `sad_blink`
- The reader treats each as a small state machine: each
  expression has a base eye shape + a blink loop

## Try it

In the Library, set `TYPE: animations` — 6 entries.  Compare with
`TYPE: math/face.py` — same intent (an expressive face) via two
very different mechanisms (data vs code).
