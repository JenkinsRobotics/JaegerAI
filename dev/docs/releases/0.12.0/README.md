# Jaeger AI 0.12.0 release evidence

Development reports, not a production certification. Commands in these reports
run from the repository root unless they explicitly name another directory.

Start with the [September 13 release candidate](RELEASE_CANDIDATE_20260913.md)
for current fixes, verification, and remaining shipment gates. The reports below
are the earlier development history:

1. [Original readiness report](RELEASE_READINESS_0.12.0.md) — historical, superseded by the review below.
2. [End-to-end production review](PRODUCTION_REVIEW_20260904.md) — findings and release gates.
3. [Multimodal hardening](MULTIMODAL_HARDENING_20260904.md) — fixes, measured comparisons, and duplex ranking.
4. [CPU-only desktop verification](DESKTOP_CPU_VERIFICATION_20260904.md) — launcher and identity checks without inference.
5. [Live desktop verification](LIVE_DESKTOP_VERIFICATION_20260907.md) — installed-app checks and recorded-input inference.

Raw evidence stays in [benchmark/results/](../../../benchmark/results/).
Reports were consolidated here from the application package; the generated
[agent contract](../../../../jaeger_ai/docs/agent_contract.md) remains in its
existing location because tooling and tests rely on that path.

The subsequent hardware check found camera-first startup caused PortAudio
failures. A later [UI/device follow-up](LIVE_DESKTOP_VERIFICATION_20260907.md#follow-up-growing-preview-and-missing-microphone--2026-09-07)
fixed startup coordination, preview growth, and microphone status reporting,
with four physical-device runs. This was separate from the cleanup below
and does not certify live duplex acoustics or overall production readiness.

## Repository cleanup verification — 2026-09-07

No runtime Python or Swift behavior was changed in this cleanup. Five release
reports moved here, folder guides and links were refreshed, and generated
Python build/lint/test clutter was moved out of the repository recoverably.
Models, instance state, benchmark evidence, compatibility seams, and native
launcher build products were retained.

- Before: `.venv/bin/python -m pytest -q` — **2713 passed, 10 skipped, 4 warnings** (119.77 s).
- After: `.venv/bin/python -m pytest -q -p no:cacheprovider` — **2713 passed, 10 skipped, 4 warnings** (119.67 s). Cache writing was disabled to keep the cleaned tree clear.
- Documentation: **136 local links checked, zero broken** across the refreshed guides and release reports before this verification section was added.
- Packaging: fresh `pip wheel . --no-deps --no-build-isolation` build and `dev/scripts/check_wheel.py` passed. Required character, icon-source, module, and contract assets were present; moved reports, bytecode, model weights, and native build caches were absent.
- Installed app: `--verify-launch` and `codesign --verify --deep --strict` passed without starting the agent or capture devices. The repository launcher symlink remains valid.
- `git diff --check` passed. No commit, push, or release was made.
