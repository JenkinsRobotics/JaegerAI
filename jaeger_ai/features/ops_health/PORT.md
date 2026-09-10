# Ops health — port notes

## Donors

| Donor | Paths | Steal |
|---|---|---|
| openclaw | `src/daemon/*`, `src/docker-healthcheck.ts`, `src/cron/*` | Supervisor loops, fail-closed probes |
| hermes-webui | `api/crash_visibility.py`, `gateway_watcher.py` | Surface crash honesty into chat face |

## Not in this commit

- Renaming leftover `ares-*` launchd labels (deferred per Matthew).
- Loading/unloading LaunchAgents from disk.
