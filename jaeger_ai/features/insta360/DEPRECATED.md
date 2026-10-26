# ⚠️ DEPRECATED — Insta360 Camera Integration

**Status:** DEPRECATED as of 2026-10-24. Scheduled for removal in v0.14.0.

**Why deprecated:** Hardware-specific integration for Insta360 cameras.
Not part of the core product; should be a plugin.

## Migration Path

### Option 1: Use Generic Camera Tools
JaegerAI's camera tools work with any camera:
- `camera_snap` — take a photo
- `camera_stream` — start a stream
- `look_at` — vision analysis

### Option 2: Community Plugin
The Insta360 integration can be maintained as a community plugin.
See `docs/EXTENSION_GUIDE.md`.

## What Will Be Removed
- `jaeger_ai/features/insta360/` — entire directory
- Insta360 tools in `main.py`

## Timeline
- **v0.13.0** (current): Deprecated, still functional
- **v0.14.0**: Removed from core

## Questions?
Open an issue on GitHub: https://github.com/JenkinsRobotics/JaegerAI/issues
