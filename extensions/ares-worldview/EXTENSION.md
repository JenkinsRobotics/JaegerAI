# ARES extension (draft)

Canonical extension shape is `ares-minecraft`. This repo is the WorldView
equivalent: a loopback sidecar plus a dashboard tab.

## Layout

| Path | Role |
| --- | --- |
| `manifest.json` | ARES extension manifest |
| `server/` | Express proxy + WebSocket (port 3001, `GET /api/health`) |
| `src/` | Cesium / React globe (Vite) |
| `dashboard/` | ARES tab HUD (sidecar health + launch notes) |

Install later by copying to `$ARES_HOME/extensions/ares-worldview` or
`ares extension install <path>`. Not wired into ARES in this draft.

## Run locally (loopback)

```bash
cd /Users/matthewjenkins/GitHub/ares-worldview
npm install
npm run dev:all
```

- Sidecar: `http://127.0.0.1:3001/api/health`
- Globe: Vite default `http://127.0.0.1:5173`

Do not bind the sidecar to `0.0.0.0`.

## Still to do before it is a real extension

1. Resolve upstream license (see `PROVENANCE.md`).
2. Serve the globe through the ARES tab instead of a separate Vite port
   (build `dist/` or reverse-proxy `/worldview/app`).
3. Add `GET /health` alias if the controller expects exactly that path
   (today health is `/api/health`, which the manifest already points at).
4. Optional MCP tools (`wv_flights`, `wv_ships`, …) once JaegerAI should
   query the globe. Not in this draft.
