# Agent access to the Mac and the live JaegerAI checkout

## Current deployment

| Agent | Active Apple container | Agent user | Live repo path |
| --- | --- | --- | --- |
| Hermes / Hermes WebUI | `jaeger-hermes-webui` | `hermeswebui` (501) | `/mnt/host/GitHub/JaegerAI` |
| OpenClaw | `jaeger-openclaw` | `node` (1000) | `/mnt/host/GitHub/JaegerAI` |

Both containers bind the Mac's actual `~/GitHub` directory read/write at
`/mnt/host/GitHub`. This is not a clone, sync job, or `/workspace` mirror. Existing
session/config mounts are preserved. `/workspace` remains the general artifact
directory. All four WebUI profiles list **JaegerAI (live Mac repo)**; the default
profile's catalog is `~/.hermes/workspaces.json`, whereas named profiles use
`~/.hermes/profiles/<profile>/webui_state/workspaces.json`.

Active IDs are in `.jaeger_ai/shared/container-workspaces.json`, read by the
supervisor and the repo-owned `scripts/hermes-container` CLI entrypoint. The host
`~/bin/hermes` is a symlink to that script. The Jaeger instance WebUI setting also
names the new Hermes container.

The old `hermes-webui-hermes-webui` and `ares-openclaw` containers remain **stopped**
for rollback. Do not start them alongside the replacements: they share state and
published ports. No original container or user session was deleted.

## Mac tools and agent awareness

Direct host endpoints use `192.168.64.1`, the Apple-container bridge, without
depending on Tailscale:

- Native Jaeger MCP: `http://192.168.64.1:8811/mcp`.
- Authenticated Mac capabilities: `http://192.168.64.1:8813/mcp`.
- Jaeger A2A card: `http://192.168.64.1:8812/.well-known/agent-card.json`.

Hermes previously had no backend for its authorized `host-hermes` route. The
installer now creates that target using the Jaeger-owned host-capability launcher
and adds `mac-host` to native Hermes MCP configuration. Existing credentials and
gateway authorization rules are preserved. OpenClaw's `ares-system` connection
keeps its existing credential and target. Its donor backend still uses the
legacy Hermes grant identity (the roots/grants match); gateway credentials and
visible target inventories remain separated.

The new `host_environment` tool returns live Mac OS/architecture/CPU/hostname,
an observation timestamp, and the canonical repository mapping. It requires the
existing `capabilities.inspect` grant and does not scan files or reveal secrets.
Grant listings are explicitly not represented as successful write tests.

`AGENT_CONTEXT.md` is installed as an idempotent managed block in Hermes' SOUL.md
and OpenClaw's TOOLS.md, preserving their existing content. It teaches the
Mac/container distinction, real paths, bounded diagnostics, and safe code-editing
handoff. Existing native sessions are not replaced. A useful chat request is:

> Check your Mac connection with host_environment and confirm your live JaegerAI
> workspace. Distinguish verified access from configured or unavailable access.

## Verified September 6, 2026

- Final full suite: **3,576 passed, 11 skipped**, one upstream `audioop`
  deprecation warning, in **102.82s**. Command:
  `.venv/bin/python -m pytest dev/tests -x -vv --randomly-seed=20260906 -o faulthandler_timeout=30 --tb=short`.
  The supervisor was paused during the suite to avoid its heartbeat writes
  tripping the live-state guard, then restored automatically. Nine new focused
  tests cover mount planning, missing shares, privilege rejection, role mapping,
  truthful host inventory, context preservation, safe write probes, configuration
  rollback, and cloud-stop compatibility. Python compilation, patch applicability,
  and `git diff --check` also passed.
- Both agents' real Linux users passed `agent-mac-check.py --write-probe`:
  source read, authenticated Mac tool discovery and call, Jaeger/Roundtable
  health, A2A card, and create/edit/read/rename/remove of their own probe.
- Mac tool discovery plus live inventory: Hermes **0.674s**, OpenClaw **0.476s**
  in the first recorded probe. Health/card calls took roughly **7–13ms**.
- In-container file operation probes: **10.7ms** Hermes, **8.7ms** OpenClaw.
  These are observed samples, not guaranteed response times.
- `verify-agent-workspaces.py`: the Mac created a temporary Python file;
  Hermes changed its value 1→2; OpenClaw read that edit and changed it 2→3;
  the Mac observed both changes. End-to-end container command times were
  **0.162s** and **0.092s**. The exclusive probe directory was removed.
- Both container users could run `git status` against the real checkout.
- Real two-turn WebUI memory checks passed for Hermes (`e4efdd7d31b1`) and
  OpenClaw (`57a00a571179`).
- Native Mac-report calls were verified in saved tool records:
  Hermes `mcp__mac_host__host_hermes_host_environment` in `73aea1a8e03b`;
  OpenClaw `ares-system__host-openclaw_host_environment` in `be3d419038c6`.
  OpenClaw's report completed in **4.71s**. Both report the Mac as Darwin/arm64
  and their own terminals as Linux.

The Hermes report exposed a separate false-truncation bug: a complete bulleted
answer without final punctuation was retried four times and surfaced as an
application error. `integrations/hermes_webui/jaeger_agent_compat.py` now trusts
the provider's `stop` for Ollama GLM **cloud** responses. Actual `length` signals
and local-model handling remain unchanged. The repaired WebUI turn ended once
with `finish_reason=stop`, with a successful host-tool result and no error.
This compatibility hook applies to WebUI-created Hermes agents, not unrelated
standalone Hermes CLI installations.

The original working Hermes image's gateway, Ollama helper, and init-script
hashes were checked before migration. The additional compatibility fix was
deployed to persistent `/apptoo` and active `/app` files, then the container was
restarted. The rebuilt image `hermes-webui:jaeger-mac-workspaces-20260906` contains
the same compatibility/runtime file hashes and is used by future migration
plans. Rebuild through `scripts/prepare-hermes-webui.py`; do not recreate from
an unpatched donor image. Donor repositories were not edited.

## Commands

On the Mac, from JaegerAI:

```sh
.venv/bin/python scripts/setup-agent-workspaces.py
.venv/bin/python scripts/verify-agent-workspaces.py
container exec --user hermeswebui jaeger-hermes-webui python3 /mnt/host/GitHub/JaegerAI/scripts/agent-mac-check.py --role hermes --write-probe
container exec jaeger-openclaw python3 /mnt/host/GitHub/JaegerAI/scripts/agent-mac-check.py --role openclaw --write-probe
```

Omit `--write-probe` for read-only diagnostics. The cross-write verifier is
explicitly a write test; it touches only its own temporary directory.

The migration command is `.venv/bin/python scripts/setup-agent-workspaces.py
--deploy`, for the legacy deployment only. It refuses to overwrite existing
managed containers. It preserves ports/users/resources/environment and mounts,
preflights new mounts before stopping services, takes private configuration
backups, and restores configuration/original containers on deployment failure.
Run maintenance only when no wanted chat is active, with the fabric supervisor
paused; restore the supervisor afterward. No database migration or model/provider
change is involved.

## Privacy approval and remaining boundaries

Direct Desktop/Documents/NAS mounts are **not enabled** in the final deployment.
The first expanded-mount attempt hit a real macOS TCC Desktop permission prompt
for `container-runtime-linux` before the VM could boot. The existing WebUI was
restored; the unused failed replacement was removed; deployment was retried with
GitHub only. The installer now makes personal mounts opt-in (`--include-personal`)
and preflights before downtime. macOS approval and a planned container update are
still required for those extra direct mounts. The existing host MCP grants for
those roots remain configured; no claim that every private/NAS operation was
tested. Missing NAS mounts are not replaced with misleading empty directories.

The Mac `.venv` must not be executed from Linux. Use a Linux environment for
container tests, and have the Mac operator run Mac-specific tests/restarts.
Ordinary source edits do not restart agents. Avoid editing live runtime state or
credentials, and use separate worktrees for concurrent code tasks. No SSH agent
forwarding or whole-home mount was introduced. Existing WebUI authentication and
published addresses were not changed.

Configuration backups and the prior launch contracts are private local files
under `.jaeger_ai/shared/workspace-migration-*`, excluded from Git. For rollback,
pause the supervisor, stop both managed containers, review the saved file index,
restore those configuration files using the installer's `restore_configuration`,
point the deployment manifest back to the legacy IDs, restart the host gateway,
then start the two original containers and verify health before resuming the
supervisor. Do not blindly restore an old backup after subsequent user edits.
