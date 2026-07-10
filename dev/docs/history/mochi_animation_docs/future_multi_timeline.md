# Future: multi-channel timelines (operator design note 2026-06-10)

**Status:** design idea — captured, NOT implemented.
**Source:** operator dictation during the Mochi reorg.

## The observation

> *mscripts kinda combined too many things into one thing I think...
> good idea, archive the legacy.  But instead of forcing everything
> into a single script, maybe a script that allows multiple
> timelines because you need to animate multiple channels at a time
> like LLM, TTS, animation, motors, etc... just an idea. Reference
> industry. But mscript is really a good foundation I think for
> motor controls since it was based on Fanuc robotics programming...
> but just an idea.*

## What this means

mscript today bundles animation timing + scripted sequences + (eventual) motor moves into one DSL.  Powerful, but overloaded — a real performance needs to coordinate:

- **LLM channel** — what to say / when to pause / which emotion to lean into
- **TTS channel** — speech playback with prosody hooks
- **Animation channel** — face / avatar frame sequences (gif/sprite/math/video)
- **Motor channel** — actuator moves (when the hardware lands)
- **Light channel** — LED patterns (when the hardware lands)

Cramming all of those into one script means every "performance" has to relearn the same syntax, and channels can't evolve independently.

## The proposal

**Split the format into two layers:**

### Layer 1 — Multi-track Timeline (general-purpose orchestrator)

A JSON / YAML format with one **track per channel**, each containing **clips** with a `t_offset_ms` + a payload typed to that channel.

Industry references:
- **OTIO** (OpenTimelineIO) — NLE-style track + clip model
- **Lottie** — Adobe's animation interchange (layers + keyframes)
- **MIDI** — multi-channel event timeline with per-channel programs
- **OSC / RTSP** — synchronised channel streams

Shape sketch:

```yaml
name: "greeting"
duration_ms: 3500
tracks:
  - kind: animation
    clips:
      - t_offset_ms:   0   duration_ms: 1000   payload: {adapter: gif,     asset: wave.gif}
      - t_offset_ms: 1000  duration_ms: 1500   payload: {adapter: math,    asset: faces/happy.py}
  - kind: speech
    clips:
      - t_offset_ms:  200  duration_ms: 2800   payload: {text: "Hi there, welcome back!", voice: af_heart}
  - kind: motor
    clips:
      - t_offset_ms:    0  duration_ms: 500    payload: {move: "wave_left"}
  - kind: light
    clips:
      - t_offset_ms:    0  duration_ms: 3500   payload: {pattern: "soft_blue_pulse"}
```

A `TimelineRunner` walks the merged event list, dispatching per-track clips on bus topics (`/act/animation`, `/act/speech`, `/act/motion`, `/act/light`) at their `t_offset_ms`.

**JROS already shipped exactly this shape** at commit `513deeb` (jaeger_os/timeline/runner.py).  Same schema can land in Mochi.

### Layer 2 — mscript (preserved, scoped down to motors)

mscript stays as the **motor-channel DSL**.  Its Fanuc-inspired motion-program style (linear moves, joint targets, dwell, conditional resume) is genuinely well-suited to actuator sequencing and shouldn't be replaced.

In the multi-channel timeline:

```yaml
- kind: motor
  clips:
    - t_offset_ms: 0
      duration_ms: 2000
      payload: {mscript: "wave_left.msc"}   # references an mscript file
```

The motor channel's payload IS an mscript reference (or inline mscript).  The TimelineRunner dispatches a `motor.execute` command with the mscript body; the motor node interprets it.

## Migration

1. **Archive** the existing mscripts that drive animation/face into `assets/mscripts/_archive/` with a README explaining the split.
2. **Adopt** the multi-track Timeline schema (port from JROS or design independently).
3. **Keep** motor-focused mscripts as a first-class motor channel input.
4. **Build** a small editor for the multi-track timeline (the GUI already has mscript editors — add a track-based view).

## Not implementing here

This doc captures the operator's idea so it's not lost.  Implementation lands when the operator says go — likely after the Mochi reorg settles and the LLM-driven animation selection (the agent picking the right Timeline file for the moment) becomes the workflow.

## Related

- `jaeger_os/timeline/schema.py` — JROS's multi-track schema (msgspec.Struct)
- `jaeger_os/timeline/runner.py` — wall-clock dispatcher
- Mochi's existing `nodes/animation/plugin_core/mscript_engine.py` — current mscript interpreter (becomes motor-only after the split)
