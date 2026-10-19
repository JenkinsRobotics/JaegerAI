# Client aliases

`macos` links to `jaeger_ai/interfaces/macos-shell`, the canonical native host. `web` links to `jaeger_ai/interfaces/ui`, the shared frontend. These are symlinks, not additional implementations. Required API/proxy services remain under `features/webui`; retired desktop and web frontend source is preserved outside the repo in the Desktop legacy archive. See `docs/integration/SCOPED_CLEANUP.md`.
