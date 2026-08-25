---
name: weights-and-biases
description: "Instrument an ML workflow with Weights & Biases for runs, metrics, sweeps, artifacts, or model registry. Use when the user explicitly chooses W&B or provides an existing W&B project."
license: MIT
compatibility: Requires the wandb package, account/API authentication, and network access.
metadata:
  jros:
    version: 2.0.0
    lifecycle: optional
    skill-class: first-class
    platforms: [linux, macos, windows]
    requires-tools: [execute_code, terminal]
    tags: [wandb, experiment-tracking, sweeps, registry]
    category: mlops
---

# WEIGHTS AND BIASES

## SOP

1. Resolve entity, project, run identity, privacy mode, metrics, config, and
   artifact-retention requirements.
2. Verify `wandb` version and authentication without displaying the API key.
3. Add the smallest instrumentation: init, immutable config, explicit metrics,
   artifact policy, and guaranteed finish/cleanup.
4. Read `references/imported-guide.md` only for the selected integration, sweep,
   artifact, table, or registry API.
5. Run a bounded smoke job and confirm it appears in the intended project.
6. Record run URL/ID and offline-sync instructions where applicable.

## ERROR HATCH

If authentication/network fails, use W&B offline mode only with user agreement;
never log secrets, raw credentials, or undeclared sensitive datasets.

## DONE WHEN

The run is reproducible, expected metrics/config/artifacts are present, and the
correct project/run identifier is reported.
