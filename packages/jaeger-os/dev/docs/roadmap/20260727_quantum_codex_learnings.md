# What JaegerOS can take from Quantum Codex

Read 2026-07-27. Quantum Codex is the operator's production framework
for real laboratory hardware — 350 Python files, ~15 devices in one
app, InfluxDB telemetry, a device catalog. It solves the same shape of
problem JaegerOS does and has been through more hardware.

Only findings that are actually adoptable. Where we are ahead, that is
said too — the point is a better framework, not a compliment.

---

## 1. Simulation-first, and it beats what we just built

**Theirs.** Every device ships two classes with the *same public
surface*:

```
DeviceProxy(**parms)      real hardware
DeviceSimProxy(**parms)   pure Python, no hardware
```

Selected by `config["app"]["simulation_mode"]` or `--real`. **Sim is
the default**, so a fresh checkout never crashes on missing hardware.

**Ours.** `sim.toml`, added today, omits the hardware nodes entirely.

**Theirs is better and I would replace mine.** Omitting a node leaves
its consumers with nothing to consume: Mochi's `sim.toml` has no
`audio_io`, so the Hearing tab stays blank and the mic meter is
untestable. A *simulated* audio node would publish synthetic frames and
the whole downstream graph would light up — which is the point of a sim
build.

**Proposal.** A `kind: driver` module may ship a sim factory beside its
real one:

```yaml
factory: jaeger_os.nodes.audio_io:make_audio_io_node
sim_factory: jaeger_os.nodes.audio_io:make_sim_audio_io_node
```

and the manifest picks:

```toml
[[node]]
id = "audio_io"
slot = "audio"
sim = true          # or inherit [app] simulation_mode
```

Default-to-sim is the harder call. It suits a lab where the hardware is
often absent; a robot that silently ran simulated motors would be a
safety problem. **Recommend opt-in per node, never a global default**,
and the startup report (below) must say which mode each node is in.

---

## 2. A structured startup report  ✅ SHIPPED

**Theirs** (their item D, shipped):

```
System: Torsional Balance Thrust Stand v3
  [OK]     newmark_nsca1       — hardware, influx enabled
  [OK]     thorlabs_kdc101     — hardware, influx enabled
  [SKIP]   system_noise        — initialize: false
Access UI at: http://localhost:5667/
```

**Ours.** Scattered log lines. `main.py --nodes` shows what *would*
run; nothing shows what *did*. The difference matters — a node can be
declared, resolved, started, and then fail its first tick.

**Adopt as-is.** Cheap, and it is the first thing an operator reads.

---

## 3. Link health is a separate question from node health  ✅ SHIPPED

**Theirs.** Every device MUST implement:

```python
def get_ste_comm_valid(self) -> bool:
    """Device-specific: ping, query, or state flag."""
```

**Ours.** `Node.health()` returns a free-form dict. Nothing *requires*
a driver to answer whether the device is reachable.

**Why it matters.** "The node is running" and "the motor controller is
answering" are different facts, and only the second one tells you the
robot is alive. Today a JP01 node whose serial link died reports
`RUNNING` forever, because its tick loop is fine — it is the link that
is not.

**SHIPPED.** `Node.link_ok()` returns `bool | None` — `None` meaning
"owns no device", correct for everything that is not a driver. A
`False` makes `health_level()` ERROR, not WARN: a driver that cannot
reach its device is not degraded, it is not doing its job, and WARN is
how a dead robot looks healthy on a dashboard. A check that RAISES
counts as down and must not take out the heartbeat carrying that news.

`NodeHealth.link_connected` already existed and was hardcoded `False`,
so every node in the system looked disconnected and the field was
worthless. It now carries the real answer, and `True` for nodes with no
device — `False` means "a link that SHOULD be up is down", which is the
only actionable reading.

`audio_io` implements it against the honest test: are FRAMES MOVING.
A stream object that exists proves nothing — an input stream stays open
and silent after the device is unplugged or CoreAudio wedges. Silence
for 2s (200 missed frames) is a dead link, with a grace window while
the device opens, because that measures 3.6s.

The module gates hold `kind: driver` to it. Engines skip, correctly.

---

## 4. Reconnect lifecycle — where we are half ahead

**Theirs** (item H, still open): typed states `OK / ALARM / OFFLINE /
RECONNECTING`, log once on transition, retry on an interval.

**Ours.** We already have the vocabulary — `HEALTH_OK`, `HEALTH_WARN`,
`HEALTH_ERROR`, `HEALTH_STALE` with severity ordering and a system
aggregate. That is the part they are missing.

What we lack is the *behaviour*: nothing attempts reconnection, and
nothing logs a transition once rather than every tick. The supervisor
restarts a dead node; it has no concept of a live node whose device
went away.

**Proposal.** Pair `link_ok()` with a reconnect policy on the node
spec, and log transitions rather than states.

---

## 5. An anti-patterns section

**Theirs.** `architecture.md` §9, "Never Do These", with wrong/right
code pairs:

```python
def _coerce_value(v): ...       # NO — use coerce_query_value()
fn = getattr(dev, command)      # NO — use invoke_device_command()
```

**Ours.** `CONVENTIONS.md` has laws, stated positively. No list of the
specific mistakes people actually make.

**Adopt.** Cheap, and it is the section a new contributor reads
fastest. Ours would start with things caught today: parsing a module's
format in an app, importing the render path in a surface, publishing
from a bus callback into a widget.

---

## 6. Where we are ahead

Worth recording so we do not "improve" backwards.

- **Slot binding.** Their config names a device class per app. Ours
  binds a capability and lets any module fill it; swapping Kokoro for
  Piper is an install, not an edit.
- **Health severity.** Their alarm states are a backlog item; ours
  ship, with aggregation.
- **QoS per topic.** They have one polling period per device. We
  distinguish a droppable frame from an e-stop that must not be.
- **A wire contract.** Their telemetry is dicts. Ours is msgspec
  structs with a registry, so a typo is a decode error rather than a
  missing key at 3am.
- **The overlay.** Nothing in Quantum shadows an installed device with
  a local copy.

## 7. Where they are ahead, beyond the above

- **Telemetry history.** InfluxDB integration is built in: every device
  streams to a time-series DB with tags. We have live health topics and
  no recorder — the same gap as `ros2 bag`, noted in the ROS
  comparison. Two independent frameworks both have this and we do not.
- **A device catalog.** ~15 devices with a documented port guide.
  Ours has three modules.
- **Their own improvement backlog is written down**, prioritised, and
  items get struck through when done. `dev/docs/reality/STATUS.md` is
  the closest thing we have and it is not a backlog.

---

## Second pass — what the first read missed

The first pass covered `architecture.md`, `framework_improvements.md`
and some code. It did not cover `motion/`, `cli/`, `services/`, or
`framework/general|utils|ste`. Two findings from those, both real.

### 8. Safety as a DECORATOR, not a notification

`motion/safety.py` wraps any `MotionController` and **is itself a
MotionController**:

```python
SafetySupervisor(inner, require_enabled=True, enforce_soft_limits=True)
```

The runtime, the UI and the API all hold the *same guarded object*, so
every move — scripted or manual — passes the checks. Guards: latched
fault/e-stop refuses all motion until cleared, an axis must be enabled
before it moves, and soft travel limits are enforced in real units.

**Ours is weaker and it is worth being clear about why.**
`EStopLatch` subscribes to `/act/estop/trigger` and calls `estop()` on
things that registered — a NOTIFICATION model. Every node must
remember to honour the latch, and a node that forgets is a node that
keeps moving. Nothing structurally prevents it.

The decorator model makes forgetting impossible: there is no unguarded
object to hold, because the only reference anyone is given is the
wrapped one.

**This is a safety-path design change, so it gets a plan and an
operator decision rather than an afternoon.** The shape for us: a
driver's adapter is wrapped at construction, and the node never sees
the raw one. It composes with `link_ok()` — a guard can refuse motion
on a dead link as readily as on a latched e-stop.

Priority: **high, and ahead of the remaining items**, because it is the
one finding that is about not hurting anyone.

### 9. Hardware discovery is a first-class CLI

`quantum-scan` / `cli/hardware_scan.py` plus
`framework/utils/device_finder.py`: scan the USB/VISA bus, print what
is attached, and emit JSON an app author can paste into a config.

**We have nothing.** Finding out what is plugged into a JP01 means
knowing already. The control plane can inspect a RUNNING system; there
is no answer for "what hardware is on this machine before I write the
manifest".

Smaller than the safety item and genuinely useful the first time
someone sets a robot up on a new machine.

### Also present, deliberately not adopted

- `services/` — grafana, influx, mongo, slack, ssl. Infrastructure
  integrations that belong in an app or a module, not a robotics
  framework's core. Ours would be modules.
- `framework/general/singleton.py`, `thread_safe.py` — utility layers
  we have equivalents for or do not need.
- `motion/mscripts` — a motion scripting language. JaegerAnimation has
  an `mscript` too and they are unrelated; worth knowing before someone
  assumes they are the same thing.

---

## Recommended order

1. ~~**Startup report**~~ — SHIPPED `6f03d81`.
2. ~~**`link_ok()` for drivers**~~ — SHIPPED `7c3a23a`.
3. ~~**Flight recorder**~~ — SHIPPED `2dd7449`, trimmed to a crash
   window in `37c2327`. Wanted by two independent comparisons.
4. **Safety as a decorator** — the only finding about not hurting
   anyone. Needs a plan and an operator decision, not an afternoon.
5. **Sim nodes** — replaces `sim.toml`'s omit-the-node approach with
   something whose consumers can be developed against.
6. **Hardware discovery CLI** — "what is plugged into this machine",
   which today you have to already know.
7. **Anti-patterns doc** — free, high leverage.
