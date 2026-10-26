# ⚠️ DEPRECATED — OIDC Authentication

**Status:** DEPRECATED as of 2026-10-24. Scheduled for removal in v0.14.0.

**Why deprecated:** OpenID Connect authentication for WebUI. Most deployments
use local auth or Tailscale. OIDC adds complexity for a niche use case.

## Migration Path

### Option 1: Use Tailscale Serve (Recommended)
Tailscale provides authentication at the network layer:

```bash
# In WebUI settings, enable Tailscale publishing
jaeger webui start --tailscale
```

### Option 2: Use Local Auth
Default local authentication with session tokens:
```bash
jaeger webui start  # Uses local session auth
```

### Option 3: Reverse Proxy Auth
Put your WebUI behind a reverse proxy with auth:
- **Caddy** with basicauth or forward_auth
- **nginx** with basic auth or OAuth2 Proxy
- **Traefik** with forwardAuth

### Option 4: Community Plugin
Maintain OIDC as a community plugin. See `docs/EXTENSION_GUIDE.md`.

## What Will Be Removed
- `jaeger_ai/features/oidc/` — entire directory
- OIDC imports in `features/webui/adapter/server.py`
- OIDC auth routes

## Timeline
- **v0.13.0** (current): Deprecated, still functional if configured
- **v0.14.0**: Removed from core

## Questions?
Open an issue on GitHub: https://github.com/JenkinsRobotics/JaegerAI/issues
