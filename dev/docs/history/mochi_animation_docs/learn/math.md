# Procedural / math animations

## What it is

A **procedural** animation has no stored frames.  The picture for
time T is computed by running a function — `f(t) → pixels`.  26 of
Mochi's 167 assets are math scripts (Python files).

This is the BIG conceptual leap.  Every previous animation type
in this Learn series stored its frames on disk; this one stores
only an algorithm.

## History

- **1960s-70s** — Mainframe demos.  John Whitney's vector graphics
  films + Larry Cuba's CGI work for *Star Wars* (1977).
  Animations as program output, not as recorded reels.
- **1980s** — The demoscene.  Cracking groups producing
  intro-screen animations in 4-64 KB, where the entire animation
  is procedurally synthesised every frame because there's no
  room for stored bitmaps.
- **1995** — Pixar's *Toy Story* — every frame procedurally
  rendered, no shot has a "stored frame" anywhere; the scene
  files describe geometry + lighting that the renderer evaluates.
- **2010s** — Shadertoy + WebGL — procedural animation
  democratised.  Anyone can write `f(uv, time)` in a browser and
  see it move.
- **Now** — Mochi's `math/` adapter is the same idea at 64×64:
  Python function returns RGB triples for each pixel given `t`,
  the renderer paints them.

## How it works

Mochi's math handler defines an interface:

```python
class MathAnimation(Animation):
    def render_into(self, timestamp: float, buf: bytearray) -> None:
        # Compute RGB for every (x, y) at this timestamp.
        # buf is W*H*3 bytes, fill it.
        ...
```

What goes inside `render_into` is up to the script.  A few
representative patterns:

| Pattern | Math | Examples in Mochi |
|---|---|---|
| **Time-varying colour fill** | `rgb = palette(t % period)` | `rainbow.py` |
| **Sweeping line/bar** | `if abs(x - speed*t) < width: rgb = on else off` | `bars.py` |
| **Cellular automata** | Game of Life, Rule 30, etc. | `game_of_life.py`, `game_of_life_2.py` |
| **Pixel-shader style** | `rgb = sin(x*kx + t) + sin(y*ky + t)` | `daft_punk_inspired_geometric.py` |
| **Feature renderer** | Eyes, face shapes computed each frame | `eyes.py`, `face.py`, `face_2.py` |

The signature trade-off: procedural animations cost CPU every
frame (no caching), but they cost zero disk + zero memory + can
be parameterised (your `eyes.py` can take a `mood` argument and
draw different eyes for the same script).

## How Mochi implements it

| File | Role |
|---|---|
| `nodes/animation/animations/math_handler.py` | Adapter that loads a Python file + exposes its main function as an `Animation` |
| `nodes/animation/animations/__init__.py` | Registers `math` mode based on `.py` extension |
| `assets/math/` | The 26 individual scripts (each one a standalone Python module) |

The flow when you fire a math animation:

1. Companion sends `node animation mode on rainbow`
2. Animation node finds `assets/math/rainbow.py` via catalog
3. `math_handler.MathAnimation` imports the file dynamically + grabs
   its render function
4. Every frame, the renderer calls that function with the current
   timestamp and pixel buffer
5. The function fills the buffer — could be a one-liner or a
   100-line shader

No frame storage anywhere.  Run forever; the file's a few kilobytes.

## The educational angle

This is where Mochi most shines as a teaching tool.  GIFs feel
magical because someone hand-drew the frames.  Math animations
feel magical because **the algorithm IS the art** — there's no
art file, no Pillow decode, no preview thumbnail, just a few
lines of Python that produce light when run.

Worked example for a workshop:

1. Show `rainbow.py` running in the mini window
2. Open the file in an editor — it's 30 lines
3. Tweak the speed constant from `0.05` to `0.5`
4. Save, refire — same animation, faster
5. Observe: you just edited the animation by editing a Python
   variable

No other animation type has this property.  GIFs need a re-export
from an art tool.  Sprites need re-packing.  Videos need re-encoding.
Math animations need you to change a number.

## Try it

In the companion app's Library tab:

- **MOOD:** ALL
- **TYPE:** math

You'll see 26 procedural Python animations.  Recommended teaching
order:

1. **`rainbow`** — the simplest looping colour palette.  Easy
   read.
2. **`bars`** — adds spatial variation (something moves).
3. **`game_of_life`** — adds state evolution across frames.  Now
   the animation has memory.
4. **`face` / `face_2`** — feature-renderer style.  Same code, but
   parameterisable into expressive characters.
5. **`daft_punk_inspired_geometric`** — full pixel-shader style.
   Mathy beauty.

## Where to dig deeper

- Shadertoy (https://www.shadertoy.com/) — community of procedural
  artists writing one `f(uv, time)` shader per work
- *The Book of Shaders* by Patricio Gonzalez Vivo (free online) —
  reads like a textbook for this whole space
- Mochi's `assets/math/face.py` — small, readable, and
  parameterisable.  Good starting point for authoring your own.
