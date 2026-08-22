# nodes/ — generic bus workers (and where hardware fits)

A **node** ([`base.py`](base.py) `Node`) is a long-lived, bus-addressable unit
of work: it subscribes to typed topics, does its job, publishes results, and
runs a `setup → tick → teardown → health()` lifecycle. The nodes here are
**generic and hardware-agnostic** — `motor/`, `light/`, `vision/`, `tts/`,
`stt/`, `animation/`, `media/`, `audio_session/`. Each peripheral node exposes
an **adapter seam** (a `Protocol` in its `adapters.py`, e.g.
`MotorAdapter.send_velocity`) with an ASCII/serial reference implementation.

## nodes/ vs hardware/ — the boundary

| | `jaeger_os/nodes/` | `jaeger_os/hardware/` |
|---|---|---|
| **What** | generic bus worker nodes + adapter `Protocol` seams | the hardware-integration *framework*: robot **packages** (builders + capability surface, e.g. JP01) + the capability registry + the byte `Transport`/`Protocol` layers |
| **Board-specific?** | No — ships in the library, carries no board wire formats | The framework is generic; a *package* (JP01) describes one specific robot |
| **Where a board adapter lives** | the `Protocol` seam it plugs into | the concrete per-board adapter (JP01-MC01 ESP32 motor, JP01-AVC01 Teensy LED, JP01-VCC01 Jetson camera) plugs into a node's adapter seam **at instance level**, not in the library |

**Rule of thumb:** a generic node that drives *some* motor → `nodes/`. The
framework that turns "this is a JP01 robot" into wired capabilities → `hardware/`.
The board-specific wire format → the instance (a per-board adapter on the seam),
never the library.

Design: [`dev/docs/hardware/JROS_HARDWARE_FRAMEWORK_PLAN.md`](../../dev/docs/hardware/JROS_HARDWARE_FRAMEWORK_PLAN.md)
(operator-approved 2026-06-12). See also [`../hardware/__init__.py`](../hardware/__init__.py).
