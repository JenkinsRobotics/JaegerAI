# Developer scripts

These entry points support development and verification. Operator deployment
scripts are indexed separately in [scripts/README.md](../../scripts/README.md).

| Script | Purpose |
| --- | --- |
| `run_tests.sh` | Select pytest marker tiers and pass through pytest arguments |
| `architecture_inventory.py` | Static JSON inventory of tracked files, Python imports, route literals, tools, stores and environment reads; `--summary` reports coverage and parse errors without importing the application |
| `check_wheel.py` | Legacy wheel-state exclusion check, retained for its callers/tests |
| `inspect_release_artifacts.py` | Current CI release-artifact inspection |
| `generate_agent_contract.py` | Generate/check `jaeger_ai/docs/agent_contract.md` |
| `dev_env.sh` | Developer environment helper; contains historical layout assumptions |
| `node_verification.py` | Manual node verification; no external filename caller found in the structural audit |
| `tts_node_test.py` | Manual TTS node probe |
| `walk_task1_bridge_confirmation.py` | Manual bridge/confirmation verification |
| `lilith_demo.py` | Character/UI demonstration |

Manual probes can start models, access audio devices, or interact with an agent.
Inspect each script's arguments and state selection before running it. They are
not interchangeable with the isolated automated suite in `dev/tests/`.

Offline `run_tests.sh` tiers replace inherited Jaeger/Hermes state overrides
with disposable directories under `/tmp` before collection. They also exclude
`dev/tests/acceptance/`. The acceptance tier requires explicit isolated
`JAEGER_STATE_DIR`, `JAEGER_WEBUI_URL`, and `JAEGER_GATEWAY_URL`; production ports
and repository/operator state roots are rejected. Its restart test remains a
failing gate until an owned-process fixture replaces operator service restarts.
An isolated database path alone does not establish ownership of a listener.

On macOS, network isolation can be checked explicitly:

```sh
sandbox-exec -p '(version 1) (allow default) (deny network*)' dev/scripts/run_tests.sh --unit
```

Swift verification must use an external `--scratch-path`. Exclude
`DispatcherLiveTests` from offline runs: those opt-in tests can contact and
restart operator services. Offline Swift success is not live-client acceptance.

Keep these paths stable while they have CI, test, documentation, or manual
workflow consumers. The two wheel checkers have different scopes; the legacy
checker is a review candidate, not a byte-identical duplicate.
