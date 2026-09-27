# JaegerAI 0.13.0 release record

**Classification:** RELEASE RECORD
**Target:** `0.13.0`
**Branch:** `0.13-dev`
**Date:** 2026-09-27

## Qualified for this release

| Gate | Result | Scope |
| --- | --- | --- |
| P0-1 — live configured-provider conversation | QUALIFIED | Resident ReAct turn, `/v1/runtime/models` truth, terminal receipt, restart continuity |
| P0-2 — streaming Stop/cancel | QUALIFIED | Stop during model phase, one terminal `cancelled` receipt, immediate next turn, restart continuity |
| P0-3 — gated tool/effect verification | QUALIFIED | Approved `write_file` independently verified; denial left file unchanged |
| P0-4 — product-path runtime qualification | QUALIFIED | Live WebUI client surface: gated effect, steering, immediate next turn, restart continuity |
| P1-5 — IDE/WebUI same-session continuity | QUALIFIED | IDE-started session survived WebUI continuation, return to IDE, and controlled restarts with identical messages and ordered receipts |

## Packaging evidence

The `0.13.0` distributions were built from a clean checkout into external
scratch, then inspected with `dev/scripts/inspect_release_artifacts.py`. The
external artifact set included:

- `jaeger_ai-0.13.0` wheel and sdist
- `jaeger_agent-1.2.0` wheel and sdist
- `jaeger_os-0.10.0` wheel and sdist
- `jaeger_kokoro_tts-0.12.0` wheel and sdist
- `jaeger_whisper_stt-0.13.0` wheel and sdist
- external `JaegerAI.app`
- external `jaeger-ide-0.1.2.vsix`

All inspected archives reported `clean`; the `.app` and VSIX contained no
runtime-state members. Installer and shell scripts passed `bash -n`, and the
canonical verification pipeline was green before and after packaging.

## Deferred to `0.14`

- P1-6 — real existing IDE-worker conversation steering.
- P2-7 — durable memory add/recall/correct/forget journey.
- P2-8 — persona continuity across provider/model changes.
- P2-9 — physical microphone/speaker voice qualification.
- P2-10 — truthful runtime presence states.
- P3-11 — phone/off-LAN field client.
- P4-12 — one real proactive workflow.
- P4-13 — final installed-artifact golden journey and rollback qualification.

## Reproducible packaging

```bash
python scripts/install-packages.py --no-install --sdist --wheel-dir "$TMP/jaeger-dist" \
  packages/jaeger-os packages/jaeger-agent packages/jaeger-kokoro-tts packages/jaeger-whisper-stt .
python dev/scripts/inspect_release_artifacts.py "$TMP/jaeger-dist"
bash -n install.sh scripts/*.sh dev/scripts/*.sh
./scripts/verify.sh
```