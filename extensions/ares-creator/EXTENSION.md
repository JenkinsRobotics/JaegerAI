# ARES Creator Studio & VTuber Engine

The `ares-creator` extension turns ARES into an autonomous content creation studio:
- Real-time VTuber face-tracking overlay for OBS/streaming.
- Automated YouTube video scripting and Remotion composition pipeline.
- Autonomous YouTube transcript extraction and knowledge ingestion.

## Architecture

- **Sidecar Daemon:** Python FastAPI (port `3849`)
- **OBS Overlay:** `http://127.0.0.1:3849/overlay/avatar`
- **Dashboard Tab:** `/creator` in ARES WebUI
- **Agent Tools:** `yt_research_video`, `generate_video_script`, `render_video_composition`

## Quickstart

```bash
cd services/controller/extensions/ares-creator
pip install -r requirements.txt
python -m server.server
```
