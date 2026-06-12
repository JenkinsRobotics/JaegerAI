"""JP01 — the first hardware package (desk-scale robot, 3 controllers).

Controllers (survey 2026-06-12, JP01_Firmware branch 2.0):

  * **mc01** — ESP32 motion controller. ``MJ[a1,a2,speed]`` servos
    (joint 1: 40-150°, joint 2: 70-105°), ``MM[s1,s2,dur]`` motors
    (firmware clamps duration ≤ 2 s and auto-neutralizes on expiry),
    ``MM[0,0,0]`` = stop. NO firmware watchdog yet (plan §2.8 L0 —
    required before live motors leave beta). No IMU.
  * **avc01** — Teensy 4.1 audio/visual controller. NeoPixel
    ``MN[mode]`` / ``FN[wrgb-hex]``; LED matrix ``MM[mode]`` /
    ``BM[brightness]`` / ``FM[rgb-hex]``; ``CN``/``DC`` handshake,
    ``ST`` status, 30 s heartbeat lines.
  * **vcc01** — Jetson vision computer. ZMQ REP commands (:5556),
    PUB telemetry (:5555/:5558), UDP video (:5001/:5003). On branch
    2.0 the Jetson owns the serial links to mc01/avc01, so this
    package's topology declares the ``relay:`` dual-path.

**Ships simulated** (``simulated: true`` on every controller —
MockTransport with firmware-shaped responders). Flipping a controller
live is a topology edit, gated on the operator walking that
capability on real hardware, and for motion additionally on the L0
firmware watchdog landing (plan §2.8).
"""
