# JaegerAI — Developer & Agent Operating Guide

This repository is a **100% modular, local-first cognitive AI platform** built on **30 standalone Python packages** and **6 standalone React 19 UI packages** under `packages/`.

## Golden Rules

1. **Zero in-repo runtime junk:** Virtual environments live outside the repo at `~/.jaeger/venv` (override via `JAEGER_VENV`), UI production builds live at `~/.cache/jaeger/ui-rebuild-mainscreen/dist`, and Python bytecode cache lives outside the repo (`PYTHONDONTWRITEBYTECODE=1`).
2. **Strict package layering:** Standalone packages under `packages/jaeger-*` MUST NEVER import `jaeger_ai`, `jaeger_agent`, or `jaeger_os`. Enforced automatically by `dev/tests/test_package_layering.py`.
3. **Zero external infrastructure daemons:** Use embedded SQLite WAL and in-process `asyncio` — no Redis, Postgres, RabbitMQ, or Docker required.
4. **32 GB Apple Silicon budget:** Respect `jaeger_orchestration.ResourceGovernor` (`OWNER_WORK > AWARENESS_SAFETY > IDLE_LIFE`), max 1 heavy model resident at a time, and hard-pruned camera frame buffers.
5. **User-owned identity:** Never hardcode personal names, channels, or founder narratives into platform code; user identity lives in `~/.jaeger/identity.json`.
6. **Fail-closed safety:** External side effects (publishing, spending, sending external messages, motor motion while E-Stop is latched) require explicit owner approval or operator E-Stop release.

## Daily Commands

```bash
./install.sh --profile full     # One-command reproducible install
./jaeger doctor                 # Verify packages, binaries, WebUI & live Gateway
./jaeger status                 # Live Gateway, 32 GB RAM, Mind Loop, Droid & Minecraft
./jaeger                        # Interactive streaming terminal chat (TUI)
./jaeger ask "<prompt>"         # Single-turn prompt against live Gateway
./jaeger start                  # Start Gateway (:33418) + 5-Tab Studio WebUI (:8790)
./jaeger open                   # Open http://127.0.0.1:8790 in default browser
./jaeger verify                 # Run full backend + frontend + build verification
```
