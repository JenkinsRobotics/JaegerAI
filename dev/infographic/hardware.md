# Hardware integration — motor · light · vision

**Status: 🟡 mixed** — vision is built (USB + TCP cameras); motor + light are skeletons (node + adapter protocol, no real device I/O in the library).

```mermaid
flowchart LR
    agent(["agent"]) -->|"/act/motion"| motor["MotorNode ✅<br/>+ MotorAdapter protocol"]
    agent -->|"/act/light"| light["LightNode ✅<br/>+ LightAdapter protocol"]
    motor -.->|"serial/USB · instance-level"| mhw["servos / ESP32 ◇"]
    light -.->|"serial/HTTP · instance-level"| lhw["LEDs / WLED ◇"]
    cam["camera"] --> vis["VisionNode ✅<br/>USB (cv2) + TCP adapters"]
    vis -->|"/sense/camera_frame"| brain(["brain / inference"])
    brain -.->|"/sense/vision_analysis"| agent
    motor -.->|"/sense/proprio · reserved"| agent
    touch["touch"] -.->|"/sense/touch · no producer"| agent

    classDef built fill:#15402b,stroke:#3fae6f,color:#eafff2;
    classDef partial fill:#473a14,stroke:#c9a13b,color:#fff7e0;
    classDef plan fill:#3a1530,stroke:#a64fa6,color:#ffe9fb,stroke-dasharray:5 3;
    class vis,cam,brain built;
    class motor,light,agent partial;
    class mhw,lhw,touch plan;
```

**Library + instance split.** The library ships universal **nodes + adapter protocols + reference serial adapters**; real device I/O is wired per robot at deploy time (subclass the adapter). So:

- **Vision — ✅ built / operational.** `USBCameraAdapter` (OpenCV `cv2.VideoCapture`) + `TCPCameraAdapter` (length-prefixed socket) are both real, latest-frame-wins, and publish `/sense/camera_frame`.
- **Motor — 🟡 skeleton.** `MotorNode` subscribes `/act/motion` and forwards to a `MotorAdapter`; `SerialMotorAdapter` formats `VEL …` / `WP …` ASCII but has **no real serial/TCP** in the library. `/sense/proprio` is reserved, not yet produced.
- **Light — 🟡 skeleton.** `LightNode` + `SerialLightAdapter` format `LED …` ASCII; **no real NeoPixel/WLED** in the library.
- **Touch — ◇** topic defined, no producer node.

**Key files:** `nodes/{motor,light,vision}/node.py` + `nodes/{motor,light,vision}/adapters.py`. **To build:** concrete device adapters per target board (the JP01 boards).
