# Pipeline: Permissions / Safety

**What it is:** the tier-based seat-belt every side-effecting tool call passes
through. A `@requires_tier` decorator tags each operation with one of six tiers;
a live `PermissionPolicy` (installed process-wide at boot) decides — by tier and
by mode — whether to allow, route to a human confirmation provider, or deny.
Primary source: `jaeger_os/core/safety/permissions.py`.

## The six tiers (`PermissionTier`, an `IntEnum`, permissions.py:63)

```
0  READ_ONLY        default-allowed reads
1  WRITE_LOCAL      local writes → confirmation
2  EXTERNAL_EFFECT  API calls with side effects → confirmation
3  HARDWARE         motor control / e-stop → confirmation (JROS)
4  PRIVILEGED       privileged system ops → confirmation
5  DEV_BYPASS       full bypass; human override only
```

## Policy modes (`PolicyMode`, permissions.py:86)

```
NORMAL     (0)  tier 0 auto-allows; 1/2/3/4 → confirmation; 5 → human override
READ_ONLY  (1)  only tier 0 allowed; anything else denies
PAUSED     (2)  nothing allowed — even reads blocked
```

One-way door: entering a *safer* mode is always permitted
(`enter_safe_mode`, permissions.py:390); *exiting* to NORMAL needs
`request_normal_mode(human_override=True)` or it raises `HumanOverrideRequired`
(permissions.py:413-429).

## The flow

```
tool call (decorated with @requires_tier(tier, skill, operation, summary))
        │  permissions.py:506  — builds a PermissionRequest template
        ▼
  current_policy().check(request)          ← permissions.py:333
        │  resolution order (current_policy, permissions.py:454):
        │    1. use_policy(...) contextvar overlay
        │    2. install_policy(...) process-wide global   ← survives worker threads
        │    3. _DEFAULT_POLICY (DenyAllProvider)         ← fail-safe
        ▼
  ┌─ mode == PAUSED ─────────────────► raise PermissionDenied
  ├─ mode == READ_ONLY & tier != 0 ──► raise PermissionDenied
  └─ mode == NORMAL:
        tier 0 (READ_ONLY)      ──────► allow (return None)
        tier 5 (DEV_BYPASS)     ──────► raise HumanOverrideRequired
        tier 1/2/3/4            ──────► confirmation.confirm(request)
                                            │  provider decides:
                                            ├─ True  → allow
                                            └─ False → raise PermissionDenied
        │
        └─ approved → wrapped fn runs (permissions.py:552 / :561)
```

## Confirmation providers (`ConfirmationProvider` protocol, permissions.py:147)

- `DenyAllProvider` (permissions.py:161) — default; `confirm()` returns `False`.
  Fail-safe: with no real provider wired, tiers 1-4 (including HARDWARE) are
  refused.
- `AllowAllProvider` (permissions.py:172) — approves every request. Used for
  `permissions.mode == "allow"` and in the shakedown/bench scoped policies.
- `ConsoleConfirmationProvider` (permissions.py:257) — interactive CLI/TUI
  prompt. Loads per-skill grants; on non-interactive stdin (`sys.stdin.isatty()`
  false) it denies without blocking so unattended runs never hang on `input()`
  (permissions.py:281-282). Answer parsing: `a…`→persist, `y…`→session
  (permissions.py:300-306).

## Per-skill grants (`PermissionGrants`, permissions.py:185)

Confirmation is **per skill, not per call**.
- `grant_session` (permissions.py:223) — in-memory, this run only.
- `grant_persistent` (permissions.py:228) — written to
  `<instance>/permissions.json` as `{"granted_skills": [...]}` (`_save`,
  permissions.py:244) and reloaded via `load` on boot (permissions.py:205).
- `revoke` (permissions.py:237) — drops the grant; skill prompts again.
- `is_granted` (permissions.py:220) — checked first in `confirm`, so an
  already-approved skill never re-prompts.

## Decorator + introspection

- `requires_tier(tier, *, skill, operation, summary="")` (permissions.py:506) —
  wraps sync and async callables; calls `current_policy().check(...)` before the
  body runs; tags the wrapper with `__lilith_permission__`.
- `get_tier` (permissions.py:571), `get_permission_request` (permissions.py:584),
  `is_tier_decorated` (permissions.py:595) — recover the tier/request from a
  wrapped callable.

Decorated tool modules (each imports `PermissionTier, requires_tier`):
`agent/tools/{background,remote,board,models,packages,code,scheduling}.py`, plus
the `computer_use_v1` / `macos_computer_v1` skills.

## Policy install (`install_policy` / `current_policy`, permissions.py:486 / :454)

`install_policy` sets both the contextvar *and* a process-wide global
`_installed_policy`, because a contextvar does not propagate into a fresh
`threading.Thread`; the TUI runs turns on a worker thread, so without the global
backstop `current_policy()` there would fall back to `DenyAllProvider` and refuse
every tier-gated tool (permissions.py:443-451).

Boot wiring of the confirmation provider from `Config.permissions.mode`
(`schemas.py:426`, `Literal["confirm","allow"]`, default `"confirm"`):
- `main.py:_confirmation_provider` (main.py:2641-2645) — `"allow"` →
  `AllowAllProvider`, else `ConsoleConfirmationProvider(instance_dir=…)`.
- `main.py:3889` / `main.py:4423` — `install_policy(PermissionPolicy(...))`.
- TUI `_install_confirmations` (interfaces/tui/app.py:450-464) — `"allow"` →
  `AllowAllProvider`, else its own spinner-aware `_TuiConfirmationProvider`.
- `core/runtime/_shakedown.py:97-102` — installs `AllowAllProvider` for shakedown.

## Hard safety gates (independent of the tier flow)

- **Credentials** — `<instance>/credentials/` secrets are read *only* through
  `get_credential(name)` / `list_credentials()` (`agent/tools/credentials.py`).
  Two enforcement layers:
  - `core/credentials.py:_check_mode` (line 63) refuses any file with mode looser
    than 0600 (`mode & 0o077`).
  - `agent/tools/_common.py:_resolve_read` (line 220) rejects direct `file_read`
    of anything under a `credentials/` dir — "use get_credential(name) instead".
- **HARDWARE e-stop** — tier-3 rides the confirmation flow, but the capability
  dispatcher also fails closed while the e-stop latch is engaged, unless the
  capability is `allow_when_latched` (`hardware/capabilities.py:9-15`, uses
  `EStopLatch`).

## Status

- **Live:** six tiers, three modes, one-way-door transitions, the decorator,
  `check`, all three providers, per-skill grants + `permissions.json` persistence,
  process-wide `install_policy` (with worker-thread backstop), boot wiring from
  `Config.permissions.mode` in CLI/TUI/shakedown, HARDWARE tier through
  confirmation, credentials + e-stop hard gates.
- **Note:** HARDWARE (tier 3) was hard-denied ("reserved for JROS") until 0.5.0;
  it now routes through confirmation (permissions.py:16-19).
