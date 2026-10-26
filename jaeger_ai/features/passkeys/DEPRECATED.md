# ⚠️ DEPRECATED — Passkeys (WebAuthn)

**Status:** DEPRECATED as of 2026-10-24. Scheduled for removal in v0.14.0.

**Why deprecated:** WebAuthn/passkey authentication for WebUI. Most deployments
use local auth or Tailscale. Adds complexity for a niche use case.

## Migration Path

### Option 1: Use Tailscale Serve (Recommended)
Tailscale provides authentication at the network layer — no app-level auth needed.

### Option 2: Use Local Session Auth
Default local authentication with secure session tokens.

### Option 3: Use OS Authentication
macOS Touch ID / password via the native Mac app.

## What Will Be Removed
- `jaeger_ai/features/passkeys/` — entire directory
- Passkey imports in `features/webui/adapter/server.py`
- WebAuthn registration/login routes

## Timeline
- **v0.13.0** (current): Deprecated, still functional if configured
- **v0.14.0**: Removed from core

## Questions?
Open an issue on GitHub: https://github.com/JenkinsRobotics/JaegerAI/issues
