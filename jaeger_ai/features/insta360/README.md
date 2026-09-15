# Insta360 Camera

Optional support for the Insta360 Link and Link 2 webcams: pan, tilt, zoom, and
capture stills or clips under agent control.

| File | What it does |
| :--- | :--- |
| `link2.py` | The camera driver. |
| `iokit_uvc.py` | Low-level macOS USB video plumbing. |
| `media_capture.py` | Taking photos and video. |
| `contracts.py` | The shapes returned (`CameraFrame`, `PTZPosition`, `AudioSample`). |
| `tools.py` | The camera tools the agent can call. |

**Turn it on:** plug the camera in. With no camera attached the feature stays
dormant and nothing else is affected.

**Check it works:** ask the agent to point the camera or take a picture.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
