# JaegerAI Product Truth Table

Authoritative status of what is **implemented & verified** today vs. **next operational milestones**.

| Capability | Status | Evidence |
|---|---|---|
| **Modular 29-Python + 5-UI Architecture** | Verified | `./scripts/verify.sh all` (153 backend + 5 frontend tests, AST layering guard, external Vite build) |
| **Persistent 24/7 Cognitive Life Loop & World Model** | Verified | `jaeger-cognition` running on Gateway startup (`/v1/cognition/state`, `/v1/cognition/perceive`) |
| **User-Owned Identity & Character Overlays** | Verified | `IdentityStore` (`~/.jaeger/identity.json`, `/v1/identity`, zero hardcoded founder identity) |
| **32 GB Resource Governor & E-Stop Cascade** | Verified | `ResourceGovernor` + 3-tier priority scheduler + E-Stop cascading across Governor, Droid, Minecraft & JP01 |
| **5-Tab Studio UI + 2D/3D VRM Avatar** | Verified | Built & served live at `http://127.0.0.1:8790` with Kokoro viseme timelines & VRM upload |
| **Autonomous Business Team & YouTube Studio** | Verified | 8 roles, spend caps, approval gates, 32 GB phased research planner, OpenTimelineIO `.otio` export, Media Archive |
| **Host Droid Mode (`Insta360 Link 2` + Mic + Speakers)** | Verified (Discovery + Capture API) | Live `/v1/droid/devices?refresh=1` detects connected gimbal camera, mics & speakers; motorized USB XU movement uses optional external `linkctl` |
| **Headless Minecraft Embodiment + Voyager Primitives** | Verified (Bridge + Skill Library) | Vendored Mineflayer bridge + 11 MIT Voyager JS primitives + SQLite WAL checkpoints & skill library; live LAN Minecraft server soak test is next |
| **Full-Duplex Voice & Live Camera VLM Soak Test** | Partial | 10-turn barge-in bridge tested in Python; continuous live microphone/speaker daemon & live OBS/Resolve MCP production runs are next |
