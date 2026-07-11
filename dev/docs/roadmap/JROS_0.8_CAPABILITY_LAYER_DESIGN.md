# JROS 0.8 — Mind↔Body capability layer (design draft — OPERATOR REVIEW REQUIRED)

> Status: DRAFT for operator approval. No implementation until OK'd (daemon-arch rule).
> The thesis: plug in a Body → the Mind gains its tools; unplug it → they vanish. No code edits.

## The surprise: most of this already exists

The 0.8 recon (2026-07-08) found the capability layer is largely BUILT, as the
`jaeger_os/hardware/` package framework — it predates the module refactor and is
*more* complete than the module→tool path:

- `topology.yaml` declares capabilities (`motion.move_joints`, `lights.set_mode`,
  `robot_vision.stream_info`, `telemetry.read`) with controllers, arg-schema refs,
  permission tiers, e-stop scope (`hardware/package.py:51` CapabilitySpec).
- `register_package_capabilities()` (`hardware/capabilities.py:228`) materializes
  them into umbrella ToolDefs at package boot — args validated per action,
  dispatch goes permission-tier → e-stop latch → link health → handler, and
  tools SELF-UNREGISTER on package shutdown.
- The agent re-snapshots its tool catalog at the top of EVERY turn
  (`jaeger_agent.py:307` `_refresh_tool_catalog`), so tools registered
  mid-session appear next turn. Dynamic surface already works.
- Availability is already fail-closed per controller: each umbrella's
  `check_fn` returns True only while the backing Link is connected.

"JP01 plugs in → agent gains motion tools" is therefore a WIRING problem,
not a framework problem. Three real gaps:

## Gap 1 — no boot root ever loads the package

`jaeger.toml`'s `[[node]] hardware_jp01` is `enabled = false` ("TUI path has no
chassis boot root yet" — pre-U3 comment; U3 fixed the underlying blocker).
Nothing on a normal agent path calls `boot_hardware("jp01")`, so capabilities
never register outside tests/dev.

**Design:** hardware packages ride the SAME mechanism as everything else now:
- Near-term (0.8): flip `hardware_jp01` to a normal supervised node (thread,
  tier 3, on_failure) in the manifest of any station that has the hardware —
  enabled per-station, not globally (a Mac mini driving JP01 enables it; a dev
  laptop doesn't). The U3 supervisor handles lifecycle/restart; boot passes the
  process bus; `register_package_capabilities` fires; next turn the agent
  sees the tools.
- With M-hardware (post-JP01-walk): the package gains a `module.yaml`
  (slot `hardware`, multi-module slot) so discovery/availability/manifest
  binding are uniform with kokoro_tts et al. The topology.yaml `capabilities:`
  block stays the tool-definition source (it's richer than module.yaml `tools:`
  — tiers, e-stop scope, arg schemas — and already proven).

## Gap 2 — the beta gate is the wrong gate

Every hardware umbrella is `beta=True` (`capabilities.py:303`): invisible
unless `JAEGER_DEV_MODE`. That's a global dev switch guarding a per-robot
safety question ("has this unit been live-verified?").

**Design:** replace beta with a **per-unit verification flag**:
- `unit.yaml` (Gap 3) records `verified: false` until the operator completes a
  live walk of that unit; the package boot reads it.
- Unverified unit → capabilities register with `beta=True` exactly as today
  (dev-mode-only — unchanged safety posture).
- Verified unit → `beta=False`; the umbrellas become normal `"hardware"`
  toolset tools, still fail-closed per-link, still e-stop-latched, still
  permission-tiered (tier gating is the real runtime protection and is
  independent of visibility).
- `jaeger hardware verify jp01` (operator command) flips the flag after a
  guided check (mirrors the 3.0 live-test checklist). Verification is per
  unit_id, not per model.

## Gap 3 — the Body has no identity record

The Mind has `identity.yaml`; the Body has only a placeholder in the firmware
alignment doc (§7.6). No code reads/writes unit identity.

**Design:** `unit.yaml` lives with the STATION (the unit's own record, like the
firmware doc sketches): `serial_number`, `unit_id`, `model: jp01`,
`hardware_revision`, `controllers: {cc01, vcc01, mc01, avc01}` (fw versions),
plus the `verified` flag from Gap 2. Package boot performs the handshake:
1. read unit.yaml → check `model` matches the package's `topology.yaml`;
2. query the live unit (CC01 `system.status` over the existing ZMQ REQ/REP)
   and cross-check controller presence;
3. mismatch → refuse to register capabilities (loud), matching fail-closed
   everywhere else.
The unit_id then tags telemetry/health (`/sense/node_health` already carries
node names; hardware nodes prefix with unit_id) — the seam that later allows
TWO bodies on one bus without collision.

## Explicitly out of scope (0.8)
- Multi-unit fleets (design leaves the seam; no code).
- Capability discovery via the skill index (push→pull convergence) — the
  umbrellas stay plain tools; discoverability polish is the skill-pipeline
  backlog's territory.
- Auto-registration of module.yaml `tools:` into the registry (module tools
  keep import-side-effect registration + availability maps; revisit with M3).

## Order of work (after operator OK + JP01 walk results)
1. unit.yaml schema + loader + handshake in jp01 boot (Gap 3 — smallest, no
   behavior change while unverified).
2. Verification flag + `jaeger hardware verify` (Gap 2).
3. Manifest enablement on the deployed station (Gap 1) + end-to-end walk:
   plug in → tools appear → e-stop latches → unplug → tools vanish.
Gates: suites, bench ≥79/81 (tool surface changes!), scenario security lane
(new tool exposure), live hardware walk with the operator present.
