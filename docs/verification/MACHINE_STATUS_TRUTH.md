> Current pinned integration qualification: [PINNED_STUDIO_QUALIFICATION.md](PINNED_STUDIO_QUALIFICATION.md). This report below is preserved historical evidence for its own named sources; its older current/final labels do not describe the new handoff. Overall product remains PARTIAL.

# Machine inventory and Safety read truth

## Current combined qualification, 2026-11-09

Read [Foreground Stop and Machine observation qualification](foreground-machine-qualification-20261109.md)
for the current combined handoff. The final documentation-only commit and tree are
identified by the handoff root README and `artifact-integrity.json`.

Foreground backend gates ran at a286; current Machine/UI/build/verification ran at
cfb. Exact non-UI source equality supports transfer, not a fresh cfb backend run.
The earlier process 17-pass/1-failure readiness result, isolated 1-pass diagnostic
and controlled 18-pass rerun all remain distinct, with cause unresolved. Current
bounded-worker UI is 973 tests/208 files, including all nine navigation controls;
earlier unrestricted 970-pass/3-failure and serial 973-pass attempts remain distinct.
Original802 broad 18-group and older UI956 results are historical only.

The foreground repair prevents false terminal cancellation reports; it does not
stop arbitrary native descendants. The Machine repair makes inventory/Safety
observations and refresh truthful; it does not qualify native permissions or
provider execution. All tabs remain **PARTIAL**. No installation, deployment,
remote PR/CI, rendered browser/phone, audio or real-provider acceptance is implied.

The remainder preserves the earlier report's chronology and source scope. Any
“current” or “final” claims below refer to that report's own historical snapshot,
not this combined handoff. Earlier foreground/Machine defect descriptions are
superseded only for the exact repaired scope in the linked report.

The Machine overview reports the existing `gateway_process_only` inventory.
It does not infer execution readiness, local platform, hardware or a daemon
from a failed, pending, unsupported or empty read. Observed host state and
producer limits remain transport-scoped. Safety requires a qualified passive
`bound_instance_policy_sources` response. Missing commissioning/grant data
remains unknown; failed reads never establish unrestricted authority.

Refresh reads both sources independently. It clears previous observations and
errors, and ignores completions after a newer refresh, source change or unmount.
The native settings controls and backend authorization contracts are unchanged.

## Reproduce without in-repository state

Use the existing matching external UI dependency checkout. No install is needed:

```sh
export JAEGER_UI_DEPENDENCIES=/absolute/external/ui-dependencies
export TMPDIR=/absolute/external/verification/tmp
export JAEGER_UI_TEST_OUTPUT=/absolute/external/verification/results
mkdir -p "$TMPDIR" "$JAEGER_UI_TEST_OUTPUT"
python jaeger_ai/interfaces/ui/scripts/build-external.py --test \
  --output-root /absolute/external/verification/ui
```

This runs the complete component suite, theme check, TypeScript, production
build and no-mock check from an isolated source snapshot, producing a source
and lockfile fingerprint in `dist/build.json`. For focused checks in that
snapshot, run Vitest on `src/machine-control`, `src/machine` and
`src/settings/LocalComputerPanel.test.tsx`.
Run `./scripts/verify.sh` using an external virtual environment and isolated
HOME, state, caches and temporary files; set `JAEGER_WEBUI_UI_DIST` to the new
external production output.

Component tests cover missing, pending, failed, empty, valid and malformed
inventory; independent Safety success/failure; unavailable and unbound policy;
refresh failure, repeated refreshes, source replacement and late completions.
They do not prove browser/phone paint, native OS permission behavior, cloud
provider execution or deployment. No live runtime operation is needed.
