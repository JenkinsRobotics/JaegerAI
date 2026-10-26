# ⚠️ DEPRECATED — CalDAV Calendar Integration

**Status:** DEPRECATED as of 2026-10-24. Scheduled for removal in v0.14.0.

**Why deprecated:** Calendar integration via CalDAV. Use the generic calendar
tools or a plugin instead.

## Migration Path

### Option 1: Use Generic Calendar Tools
- macOS Calendar via `macos_computer` skill (AppleScript)
- Google Calendar via API tools
- Generic `.ics` file parsing

### Option 2: Community Plugin
Maintain as a community plugin. See `docs/EXTENSION_GUIDE.md`.

## What Will Be Removed
- `jaeger_ai/features/caldav/` — entire directory
- CalDAV tools in `main.py`

## Timeline
- **v0.13.0** (current): Deprecated, still functional
- **v0.14.0**: Removed from core

## Questions?
Open an issue on GitHub: https://github.com/JenkinsRobotics/JaegerAI/issues
