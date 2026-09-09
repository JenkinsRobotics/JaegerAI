# Operator and integration scripts

This directory contains the public installer and the entry points used to deploy,
run, and verify the shared agent stack. Developer-only tooling is indexed in
[dev/scripts/README.md](../dev/scripts/README.md).

## Installation and running services

| Script | Purpose |
| --- | --- |
| `install.sh` | Public curl bootstrap; invokes the root local installer |
| `run-jaeger-webui.sh` | Launch the pinned standalone Jaeger WebUI |
| `prepare-hermes-webui.py` | Assemble the pinned WebUI plus Jaeger container overlay |
| `run-host-tools-gateway.sh` | Launch the existing host-tools gateway |
| `run-host-capability-server.py` | Host capability service compatibility launcher |
| `run-hermes-native-api.py` | Start Hermes' native API inside its container |
| `hermes-native-api-service.py` | Host launcher for that container API |
| `hermes-container` | Convenience wrapper for the deployment-selected Hermes container |

## Setup and migration

| Script | Purpose |
| --- | --- |
| `setup-agent-workspaces.py` | Managed container/workspace migration |
| `expand-agent-workspaces.py` | Explicit expanded workspace migration |
| `setup-hermes-native-api.py` | Install the native API service |
| `setup-native-runs.py` | Configure native Runs integration |

Setup scripts can change deployment state. Read the corresponding
[integration instructions](../integrations/hermes_webui/README.md) and
[workspace migration notes](../integrations/agent_workspaces/README.md) before
using them. Ordinary startup does not require rerunning setup.

## Verification

| Script | Purpose |
| --- | --- |
| `agent-mac-check.py` | Host/workspace connectivity diagnostics; write probes are explicit |
| `verify-agent-webui.py` | Live profile routing and two-turn recall |
| `verify-native-webui.py` | Live tool events and approval-denial handling |
| `verify-hermes-native.py` | Direct native Hermes verification |
| `verify-openclaw-native.py` | Direct native OpenClaw verification |
| `verify-roundtable-native.py` | Native Roundtable verification |
| `verify-agent-workspaces.py` | Cross-agent workspace verification |
| `verify-host-nas.py` | NAS filesystem diagnostics |

Live checks may create labeled sessions, consume model tokens, or perform
explicit filesystem probes. Use the deployed endpoint and configured model
selection; inspect each script before execution. These scripts are distinct
checks, not interchangeable copies. The structural audit found no byte-identical
scripts and retained even manual scripts without direct code callers.

## Stable entry points

Do not move `scripts/install.sh`: its raw URL is a public installation contract.
Root `install.sh` installs an existing checkout; root `run.sh` and `jaeger`
launch the runtime/CLI. Installed launchd services, container commands, tests,
and integration documentation reference other paths in this directory, so path
changes require coordinated updates. See the
[repository triage](../dev/docs/reality/REPOSITORY_TRIAGE_2026_09_08.md) for evidence.
