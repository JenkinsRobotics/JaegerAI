# Safety checklist — walk before any live (non-simulated) run

> Walk this start to finish, live, at the hardware — the same
> "inspection is not verification" doctrine as everything else in this
> ecosystem (`CONVENTIONS.md` → "Walk the flow before shipping", and the
> JP01 3.0 live-test checklist this one mirrors). Reading this file is
> not completing it. Do not set `unit.yaml`'s `verified: true` until
> every box below is actually checked, by a human, present at the unit.

Fill in the TODOs as you go; keep this file (renamed per-unit if you
bring up more than one) as the durable record of the last verified walk.

## 0. Which unit, which topology

- [ ] `unit_id`: `____________________` (matches `unit.yaml`)
- [ ] `topology.yaml`'s `package:` matches `unit.yaml`'s `model:`
- [ ] Every controller in `topology.yaml`'s `controllers:` has a
      corresponding entry in `unit.yaml`'s `controllers:` (firmware
      version recorded, not left as `TODO-fw-version`)

## 1. E-stop scope — named and tested

- [ ] `topology.yaml`'s `safety.estop_scope` lists **every** controller
      capable of causing physical harm (moving parts — not lights, not
      read-only sensors). List them here for the record:
      `____________________`
- [ ] Triggered `motion.stop` (or this workspace's equivalent) with the
      unit live and confirmed every scoped controller actually went
      neutral (motors stopped, not just acknowledged over the wire)
- [ ] Confirmed the e-stop **latches** — a second unrelated command is
      refused while latched, and only an explicit operator release
      clears it (never an agent action)
- [ ] Confirmed a capability marked `allow_when_latched: true` is
      *only* the stop capability itself — nothing else in
      `topology.yaml` carries that flag

## 2. Firmware watchdog status

- [ ] `topology.yaml`'s `safety.firmware_watchdog_required` reflects
      reality: `true` if any e-stop-scoped controller has **no**
      independent L0 hardware watchdog yet, `false` only once it does
- [ ] If `true`: confirmed `bringup/boot.py`'s warning actually prints
      on a LIVE (non-simulated) boot — silence here would be a bug, not
      good news
- [ ] Recorded the plan (or ticket/date) for when the watchdog ships,
      if it hasn't: `____________________`

## 3. Permission-tier review

Walk every entry in `topology.yaml`'s `capabilities:` list and confirm
the tier matches reality — an under-tiered capability is a safety bug,
not a style nit:

- [ ] Every capability that can move/actuate something physical is
      `HARDWARE`, not `WRITE_LOCAL`
- [ ] Every `WRITE_LOCAL` capability is genuinely safe to run while the
      e-stop is latched (status lights: yes; anything that moves: no)
- [ ] Every `READ_ONLY` capability really only reads — no side effect
      hiding in a "status" handler
- [ ] Every capability's `description` matches what the firmware
      actually does, including real clamps/ranges (no aspirational
      copy — CONVENTIONS.md "No spec ahead of code")

## 4. The live walk itself

- [ ] Ran `bringup/boot.py`'s `load()` against the REAL unit (not the
      simulator) at least once, present at the hardware, hand on a
      physical kill switch / power cutoff independent of software
- [ ] Exercised every `HARDWARE`-tier capability at least once, live,
      and confirmed the physical result matched the tool's response
- [ ] Confirmed a dead/disconnected link degrades a capability to
      failing closed (tool call refused with a clear error), not a
      silent no-op or a crash
- [ ] Confirmed telemetry (`telemetry.read` or equivalent) reflects
      real, current hardware state — not stale/cached values presented
      as live

## 5. Sign-off

- [ ] Walked by: `____________________`   Date: `____________________`
- [ ] `unit.yaml`'s `verified` flipped to `true` **only after** every
      box above is checked
- [ ] Re-run this checklist (flip `verified` back to `false` in the
      meantime) after any hardware change: new controller, re-flash,
      repair, or firmware update to anything in `estop_scope`
