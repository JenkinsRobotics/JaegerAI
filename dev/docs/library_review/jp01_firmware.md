# Library review — `JP01_Firmware`

**Source:** `/Users/jonathanjenkins/GITHUB/JP01_Firmware`
**Maintainer:** operator (Jenkins Robotics)
**Status:** in development, hardware test platform
**Reviewed:** 2026-06-06 for 0.4 roadmap inputs

---

## What it is

JP01_Firmware is the **physical robot's existing firmware**, predating
JROS's agentic-AI layer.  It's a hardware test platform — no LLM, no
agent loop, just the boards talking to each other.  When JROS matures,
JP01_Firmware's controllers become the "body" that the JROS brain
drives.

## Board layout (the source of truth for 0.4 hardware adapters)

The repo organises one controller per directory under `controllers/`:

| Controller | Board | Role |
|---|---|---|
| **JP01-VCC01** | Jetson Orin | Vision / AI / Central Compute / PC interface |
| **JP01-AVC01** | Teensy 4.x | Audio / Video / LED matrix (`.ino` firmware) |
| **JP01-MC01** | ESP32 | Motion controller (motors + sensors) |
| **JP01-CC01** | (host PC, today a Mac) | Operator-facing manual Python UI: connect to + control individual components.  **0.4 deliverable: JROS REPLACES CC01.**  The Mac running JROS becomes the new Central Computer; what was a manual control panel becomes an autonomous agent that drives the other three boards via the same serial / network protocols CC01 already speaks. |

**Important correction to my earlier 0.4 roadmap:** I had Teensy as
motors and ESP32 as LEDs.  JP01 actually does the opposite — **Teensy
runs the audio/LED stack, ESP32 runs the motors.**  Fixed in the
roadmap library-queue update.

**On CC01 specifically:** confirmed by the operator that JP01-CC01
is currently a manual Python UI an operator runs on a host PC to
connect to + control individual components.  JROS on the Mac is the
intended replacement — same role (central computer + operator-
facing surface) but with autonomous agentic control.  This means
Track C's hardware-adapter nodes don't just talk to MC01/AVC01/VCC01
— they collectively SUPERSEDE CC01.  The CC01 codebase is therefore
also a reference for the current operator-control vocabulary the
JROS surface should support (per-component connect/control
operations).

## Patterns to absorb into JROS 0.4

### 1. The board naming convention

Use the JP01 prefix in topic schemas + node names so JROS nodes line
up 1:1 with the firmware controllers:

```
/sense/audio_in    ← published by JP01-AVC01 (Teensy mic)
/act/audio_out     ← consumed by JP01-AVC01 (Teensy speaker / WS2812)
/act/motion        ← consumed by JP01-MC01 (ESP32 motor driver)
/sense/proprio     ← published by JP01-MC01 (encoder + IMU)
/sense/camera_frame      ← published by JP01-VCC01 (raw CSI cam frames)
/sense/vision_analysis  ← published by JP01-VCC01 or downstream inference
```

This is just a naming convention but it means a future "where does
sound out come from on this Jaeger?" question maps directly to a
firmware repo path.

### 2. Jetson Orin as the brain co-location candidate

The Jetson side (`controllers/JP01-VCC01/`) already runs Python with:

  - `main.py` Flask web interface
  - `camera.py` dual CSI camera streaming
  - `connections.py` serial comm with the Teensy + ESP32
  - `blackbox_logger.py` ("black box" diagnostic log pattern)
  - `install_dependencies.sh` + `requirements.txt`

If the brain ever co-locates on Jetson (open question #1 in the
roadmap), it'd land alongside this code.  For 0.4 we keep the brain
on the Mac, but the Jetson is the eventual fallback for un-tethered
operation.

### 3. The "blackbox_logger" pattern

`controllers/JP01-VCC01/blackbox_logger.py` + `BLACKBOX_README.md` —
JP01 has a structured per-event diagnostic logger separate from the
operational log.  Worth porting to JROS for the per-node health
records (Track D).  Aircraft-style "black box" gives a real post-
mortem after any crash, not just stdout tails.

### 4. CSI camera + YOLOv8 stack (already in tree)

`yolov8n.pt` sits at the repo root.  The Jetson is doing object
detection today.  When JROS adds the `vision` node (Track C, 0.4.1),
the wire format should be YOLOv8-compatible bounding boxes by default
so JP01's existing inference output drops into the topic stream
without translation.

### 5. The web interface (ReactPy)

`controllers/reactpy_template/` is the operator's web monitoring
layer.  JROS's Track F topic inspector should consider either:

  - **adopt ReactPy** so the operator has one web UI vocabulary across
    JP01 and JROS, or
  - **make the JROS inspector a ReactPy frontend** that subscribes to
    JROS topics over WebSocket and shares styling with JP01.

This is a cosmetic-but-real consolidation win.

## Patterns we should NOT inherit

  - **No agentic layer.**  JP01 was never built as an agent host — it
    polls + serves data.  JROS provides the missing brain.  Don't
    drag JP01's existing main.py into JROS as the agent loop entry.
  - **Direct Flask web server in the brain.**  JP01-VCC01's Flask
    server runs on the Jetson today.  JROS should NOT run a web
    server in the brain process — the inspector node (Track F) is
    the proper place for that.

## How JP01_Firmware informs Track C (0.4.1 hardware adapters)

The 0.4.1 work has a head start because JP01 already speaks the
serial protocols:

  - `controllers/JP01-MC01/` — read this for the existing motor
    command frame format.  The JROS `motor_ctrl.py` node should be a
    USB-CDC client of THIS protocol, not a fresh design.
  - `controllers/JP01-AVC01/JP01-AVC01.ino` + `NeoPixelHandler.h` /
    `LedMatrixHandler.h` — read these for the existing LED + audio
    frame layout.  JROS's `led_ctrl.py` and `audio_io.py` nodes wrap
    these.

**0.4.1 task: produce a `dev/docs/library_review/jp01_protocols.md`**
that documents each board's wire protocol pulled from these firmware
files, so the JROS adapter nodes can be written from a spec rather
than from reading `.ino` files every time.
