# Operator and integration scripts

This directory contains the public installer and the entry points used to deploy,
run, and verify the shared agent stack. Developer-only tooling is indexed in
[dev/scripts/README.md](../dev/scripts/README.md).

## Installation and running services

| Script | Purpose |
| --- | --- |
| `install.sh` | Public curl bootstrap; invokes the root local installer |
| `run-jaeger-webui.sh` | Launch the first-party Jaeger WebUI |
| `run-host-capability-server.py` | Host capability service compatibility launcher |
| `run-hermes-native-api.py` | Start the Hermes Agent native API from the host checkout |
| `hermes-native-api-service.py` | Host launchd entry point for the Hermes Agent API |
| `deploy-live-mac-studio.sh` | Deploy the exact pushed `master` commit to the Mac Studio and verify the public UI |

## Setup and migration

| Script | Purpose |
| --- | --- |
| `setup-agent-workspaces.py` | Managed container/workspace migration |
| `expand-agent-workspaces.py` | Explicit expanded workspace migration |
| `setup-hermes-native-api.py` | Install the native API service |
| `setup-native-runs.py` | Configure native Runs integration |
| `migrate-webui-config.py` | Remove retired Hermes WebUI container settings during upgrade |

Setup scripts can change deployment state. Read the corresponding
[workspace migration notes](../integrations/agent_workspaces/README.md) before
using them. Ordinary startup does not require rerunning setup.

## Live Mac Studio release

The operator deployment currently uses the default branch directly. After a
change is tested, commit and push it to `master`, then run:

```bash
./scripts/deploy-live-mac-studio.sh
```

The command refuses dirty, unpushed, or non-`master` source. It fetches the
same commit on the Studio, installs frontend dependencies, builds the canonical
UI, backs up the served bundle, restarts the managed Gateway/agent/Web UI/MCP
stack, and verifies the running commit plus source/served/public HTML hashes.
It rolls the source and UI back if post-cutover verification fails. A pushed
commit is not considered delivered until this command succeeds.

## Verification

| Script | Purpose |
| --- | --- |
| `agent-mac-check.py` | Host/workspace connectivity diagnostics; write probes are explicit |
| `verify-agent-webui.py` | Live profile routing and two-turn recall |
| `verify-native-webui.py` | Live tool events and approval-denial handling |
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
changes require coordinated updates.
