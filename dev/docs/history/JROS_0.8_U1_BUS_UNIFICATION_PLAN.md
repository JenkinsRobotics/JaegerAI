# JROS 0.8 — U1: bus unification (delete app/bus, repoint chassis onto transport)

> subagent-driven; checkbox steps. Spec: JROS_0.8_MODULE_REFACTOR_SPEC.md (Phase U).

**Goal:** One bus stack. The app chassis (`jaeger_os/app/`) stops using its
duplicate `jaeger_os/app/bus/` and uses `jaeger_os/transport/` — the same bus the
real nodes already run on. `transport.InProcBus` is a drop-in superset of
`app/bus/inproc.py` (adds `request()`, passes objects through untouched).

**Scope decision (confirmed low-risk):** both chassis configs run `backend =
"inproc"` (`jaeger.windowed.toml:32`, `jaeger.toml:82`) — the chassis-ZMQ path is
unexercised, so it is DROPPED (transport's ZMQ is the canon when U3's
cross-process supervision needs it). The 11 chassis messages in `core/messages.py`
stay plain dataclasses — transport's inproc bus reads only `msg.topic` and
delivers the live object, so no msgspec conversion is needed. U1 repoints the bus
*type* only; merging the node/chassis bus *instances* (and resolving the
`Transcript`/`NodeHealth` same-topic overlaps that would then activate) is U3.

**Gates:** full pytest suite green; routing bench ≥79/81; the windowed app boots.

---

### Task 1: repoint the chassis onto transport + delete app/bus + update tests

**Files:**
- Modify: `jaeger_os/app/app.py` (bus construction → transport; drop ZMQ branch + `registry`)
- Modify: `jaeger_os/core/messages.py` (drop `MessageRegistry`; keep the 11 message dataclasses)
- Modify: `jaeger_os/core/windowed.py`, `jaeger_os/interfaces/tui/__main__.py` (drop the `registry=MESSAGES` arg to `JaegerApp`)
- Delete: `jaeger_os/app/bus/` (`api.py`, `inproc.py`, `zmq.py`, `__init__.py`)
- Modify: the ~9 test files importing `jaeger_os.app.bus` (repoint to `jaeger_os.transport`)

**Interfaces (unchanged for callers):** `JaegerApp` still exposes `self.bus` with
`publish/subscribe/unsubscribe/close` (+ now `request()`); `app/core.py`,
`surfaces.py`, `supervisor.py`, `health.py` are untouched (they take `bus: Any`).

- [ ] **Step 1 — app.py bus construction.** In `jaeger_os/app/app.py`: replace `from .bus.inproc import InProcBus` / `from .bus.api import Bus, MessageRegistry` with `from jaeger_os.transport import Bus, InProcBus`. In `_build_bus` (~:192-203): remove the `if spec.bus.backend == "zmq"` branch entirely (the `Broker`/`ZmqBus` import + construction); always `self.bus = InProcBus()`. Remove the `registry` constructor param (:64,:74) and `self.registry` (dead once ZMQ is gone). If `BusSpec` in `manifest.py` has `xsub`/`xpub`/`backend` fields that are now unused, leave the schema (a config knob may still read `backend`) but the code ignores non-inproc — OR (cleaner) if `backend` is only ever "inproc", note it; do not delete manifest fields in this task.

- [ ] **Step 2 — core/messages.py registry-free.** Remove `from jaeger_os.app.bus.api import MessageRegistry` (:19) and the `MESSAGES = MessageRegistry(); MESSAGES.register_all([...])` block (~:140-146). KEEP all 11 `@dataclass` message definitions (they're imported + published/subscribed elsewhere). If any code imports `MESSAGES` from here, grep and remove those usages (they were only for the ZMQ registry): `grep -rn "from jaeger_os.core.messages import.*MESSAGES\|messages.MESSAGES\|import MESSAGES" jaeger_os/`.

- [ ] **Step 3 — drop `registry=` at the two call sites.** `jaeger_os/core/windowed.py:26` and `jaeger_os/interfaces/tui/__main__.py` construct `JaegerApp(..., registry=MESSAGES)` — remove the `registry=MESSAGES` kwarg (and the now-unused `MESSAGES` import). Grep for any other `JaegerApp(` construction: `grep -rn "JaegerApp(" jaeger_os/ --include=*.py`.

- [ ] **Step 4 — delete the package.** `git rm -r jaeger_os/app/bus/`.

- [ ] **Step 5 — update tests.** Repoint every test importing `jaeger_os.app.bus`:
  - `from jaeger_os.app.bus.inproc import InProcBus` → `from jaeger_os.transport import InProcBus`
  - `BusOverflowError` → `InProcBusOverflowError` (import from transport)
  - `from jaeger_os.app.bus.zmq import Broker, ZmqBus` → transport's `Broker`/`make_bus_for_node` (or delete the chassis-zmq test if it only tested the dropped path — a chassis-zmq test now tests nothing; remove it and note it)
  - `MessageRegistry`/`RawMessage` tests (`test_app_format.py`, `test_messages.py`, `_worker_node.py`): the registry is gone — remove/replace those specific assertions (the messages are now just dataclasses on a pass-through bus; test publish→subscribe delivery instead). Files (from the map): `test_session_trust.py`, `test_messaging_shared.py`, `test_approval_routing.py`, `test_bridge.py`, `test_windowed_app.py`, `test_app_format.py`, `test_messages.py`, `_worker_node.py`. READ each and repoint minimally; do not weaken unrelated assertions.

- [ ] **Step 6 — full suite green.** `.venv/bin/python -m pytest dev/tests -q` (expect green; the message-model + windowed tests were the ones touched). Note any pre-existing native-teardown flake per the F1 pattern.

- [ ] **Step 7 — windowed boot smoke (headless).** Confirm the windowed app constructs its bus + core without the registry: `.venv/bin/python -c "import jaeger_os.core.windowed as w; print('windowed import OK')"` and, if a headless boot entry exists, exercise `JaegerApp(...).boot()` far enough to build the bus (or a focused unit test that builds `JaegerApp` from `jaeger.windowed.toml` and asserts `app.bus` is a `transport.InProcBus`). Do NOT launch Qt.

- [ ] **Step 8 — commit.**
```bash
git add -A
git commit -m "0.8 U1: one bus — chassis on transport.InProcBus; app/bus deleted, chassis-ZMQ dropped"
```

## Done criteria
- `jaeger_os/app/bus/` gone; `grep -rn "app.bus" jaeger_os/` returns nothing in shipping code.
- Chassis builds `transport.InProcBus`; the 11 messages still publish/subscribe (dataclasses on the pass-through bus).
- Full suite green; **routing bench ≥79/81** (run separately); windowed import/boot smoke passes.

## Next: U2 (one Node/NodeState + one NodeHealth), then U3 (Supervisor manages the real nodes on the app bus — where the instance merge + Transcript/NodeHealth overlap get resolved).
