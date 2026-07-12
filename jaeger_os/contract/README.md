# `jaeger_os/contract/` — the one wire truth

0.9 structural work, step 1 (`dev/docs/vision/THREE_TIER_STRUCTURE.md`).
This package is the ONE place topic names, wire schemas, ports, packet
formats, the client protocol, and the module/capability contract types
live. It imports nothing from the rest of `jaeger_os` — stdlib + msgspec
only (enforced by `dev/tests/jaeger_os/contract/test_no_inward_imports.py`).

## Contents

| File | What | Loader lives at |
|---|---|---|
| `topics.py` | Bus topic name constants + msgspec schemas | `jaeger_os.transport` (Bus machinery) |
| `protocol.py` + `protocol_v1_fixtures.json` | Client NDJSON wire protocol frames | `jaeger_os.interfaces.bridge` / `.client` |
| `capability.py` | `PackageSpec`/`ControllerSpec`/`CapabilitySpec`/`LinkSpec`/`RelaySpec`/`SafetySpec` | `jaeger_os.hardware.package` |
| `modules.py` | `ModuleSpec` (module.yaml shape) | `jaeger_os.core.modules` |
| `ports.py` | Named port constants | — |
| `wire.py` | Named packet-format + audio constants | — |

## Who must import (or vendor) this package

**JP01_Firmware** (Mac + Jetson sides, separate repo) is the first
out-of-tree consumer. Both sides currently carry their OWN copies of
values this package now centralizes — that duplication is the "drift-bug
factory" the JP01 field week burned trust on. JP01_Firmware's session
should either add `jaeger_os` as a dependency and import
`jaeger_os.contract`, or vendor just this package (no inward imports, so
vendoring is safe — nothing else drags in).

### Constants JP01_Firmware currently duplicates

From `contract.ports`:

* `JP01_VCC01_CMD_PORT` = 5556 — ZMQ REP command channel (Jetson relay)
* `JP01_VCC01_TELEMETRY_PORT` = 5555 — ZMQ PUB telemetry
* `JP01_VCC01_VISION_TELEMETRY_PORT` = 5558 — ZMQ PUB vision telemetry
* `JP01_VCC01_VIDEO_UDP_PORTS` = (5001, 5003) — UDP video stream

These are real measured values (survey 2026-06-12, JP01_Firmware branch
2.0) — see `jaeger_os/hardware/packages/jp01/topology.yaml` (this repo's
declarative source of truth for JP01's own wiring) and
`jaeger_os/hardware/packages/jp01/adapters/vcc01.py`'s module docstring.
JP01_Firmware's zmq_client.py / vision server code is where the SAME
numbers currently live a second time, on the other side of the wire.

Ports **5560, 5570, 5571** appeared in the operator's original grep list
for this task but were NOT found anywhere in this repo (code, YAML, or
docs) — grepped `5555|5556|5558|5560|5001|5003|5570|5571|8765` across
`jaeger_os/` and found no hits for 5560/5570/5571. If JP01_Firmware uses
them, they're firmware-repo-only today; add them to `contract.ports` when
that session identifies the real call sites (don't guess the values here).

From `contract.wire`:

* `LENGTH_PREFIX_FORMAT` / `LENGTH_PREFIX_SIZE` — the 4-byte big-endian
  length-prefix framing shape. Not currently used by any JP01 wire path in
  this repo (VCC01's command channel is JSON-line over ZMQ REQ/REP, not
  length-prefixed) — listed here in case JP01_Firmware's video/telemetry
  UDP framing uses the same shape; verify against the firmware source
  before assuming.
* `AUDIO_IN_SAMPLE_RATE_HZ` / `AUDIO_OUT_SAMPLE_RATE_HZ` — not JP01-specific
  (voice pipeline, Mac-side), listed for completeness.

### What did NOT move

`jaeger_os/hardware/protocol.py` (the `AsciiBracketProtocol` / `Protocol`
ABC — MC01/AVC01 serial framing) stays in `hardware/` — it's link
MACHINERY (an implementation), not a wire-truth TYPE or constant, and it's
already JROS-side-only (JP01_Firmware speaks the same ASCII-bracket shape
independently; there is no shared code today, only a shared convention
documented in `jaeger_os/hardware/packages/jp01/__init__.py`).

`topology.yaml`'s own port values were left as declarative YAML data (this
repo's single copy) rather than rewritten to import Python constants —
YAML can't import Python, and the duplication risk this package addresses
is cross-repo (JROS vs JP01_Firmware), not intra-repo.
