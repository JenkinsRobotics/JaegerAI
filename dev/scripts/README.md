# Developer scripts

These entry points support development and verification. Operator deployment
scripts are indexed separately in [scripts/README.md](../../scripts/README.md).

| Script | Purpose |
| --- | --- |
| `run_tests.sh` | Select pytest marker tiers and pass through pytest arguments |
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

Keep these paths stable while they have CI, test, documentation, or manual
workflow consumers. The two wheel checkers have different scopes; the legacy
checker is a review candidate, not a byte-identical duplicate.
