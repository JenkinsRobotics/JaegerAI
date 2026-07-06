# Pipeline: Transport / Bus (nodes ↔ surfaces)

**What it is:** how JROS nodes and operator surfaces exchange typed
messages — a small publish / subscribe / request Bus with two
interchangeable backends (in-process queue vs ZMQ pub/sub), so a Node
never knows whether its peer is a thread or a subprocess.

Note: there are **two parallel Bus stacks** in the tree today, each
with its own `Bus` ABC, `InProcBus`, `ZmqBus`, and `Broker`:
- `jaeger_os/transport/*` — the **typed transport**: `msgspec.Struct`
  topic schemas, per-topic JSON/MessagePack codec, `request()` RPC.
  Used by the brain-side node runtime (`jaeger_os/nodes/runtime.py`).
- `jaeger_os/app/bus/*` — the **chassis (app-shell) bus**: dataclass
  messages + a `MessageRegistry`, wired by `JaegerApp._build_bus`
  (`jaeger_os/app/app.py:192`). This is the one `make_bus_bridge`
  bridges to Qt.

They do not share code; they share a shape.

## The flow

```
                     ┌──────────── the Bus interface (both stacks) ─────────────┐
   publisher ──publish(msg)──▶  delivery thread  ──fan-out──▶  subscriber cb(msg)
                              (drains one queue/socket, catches
   request(req, ack_topic) ─▶  callback exceptions so one bad sub
        │  subscribe ack, publish,  never wedges the bus)
        └─ block on Event until cid-matched ack  (transport stack only)

  MONOLITHIC  (./launch, default)          MULTIPROCESS (./launch --mode
  ───────────────────────────────           multiprocess — NOT yet operational)
  InProcBus: one queue.Queue(2048),         ZMQBus per process, all CONNECT to a
  put_nowait → delivery thread →            single XSUB/XPUB Broker proxy:
  Python subscriber callbacks.
  Zero serialization (objects pass            publishers ─CONNECT→ XSUB ─┐
  through by reference).                                                 │ zmq.proxy
                                              subscribers ←CONNECT─ XPUB ←┘
  transport codec picks the wire form
  ONLY on the ZMQ path:                      wire frame = [ topic bytes | payload ]
    text topics   → msgspec.json             SUB prefix-filters on frame 0;
    binary topics → msgspec.msgpack          frame 1 decoded per topic.

  ── bus → Qt bridge (GUIs) ──
  make_bus_bridge(bus, topics): a QObject with a `message = Signal(object)`;
  each bus callback emits the signal (Qt queues it across the delivery thread →
  the GUI thread). The ONLY sanctioned bus→widget hop.
```

## Key files / functions

- **Bus interface (transport)** — `jaeger_os/transport/bus.py` :: `Bus`
  (ABC). Five abstract methods: `publish`, `subscribe`, `unsubscribe`,
  `request`, `close`. `SubscriberFn = Callable[[TopicMessage], None]`.
- **Bus interface (chassis)** — `jaeger_os/app/bus/api.py` :: `Bus`
  (ABC): `publish` / `subscribe` / `unsubscribe` / `close` — **no
  `request`**. Same file holds `MessageRegistry` (topic→dataclass wire
  decode) and `RawMessage` (delivered when a wire topic isn't
  registered, `api.py:22`).
- **InProc (transport)** — `jaeger_os/transport/inproc_bus.py` ::
  `InProcBus`. `queue.Queue(maxsize=2048)`; `publish` is `put_nowait`
  and raises `InProcBusOverflowError` on a full queue (never blocks the
  publisher). One `inproc-bus-delivery` thread fans out; subscriber
  exceptions are caught + printed to stderr (`_delivery_loop`,
  line 149). `request()` (line 100) subscribes an ack callback, publishes,
  waits on a `threading.Event`, matches on `correlation_id`, unsubscribes
  in `finally`.
- **InProc (chassis)** — `jaeger_os/app/bus/inproc.py` :: `InProcBus`,
  `BusOverflowError`. Same queue+thread model, minus `request`.
- **ZMQ (transport)** — `jaeger_os/transport/zmq_bus.py` :: `ZMQBus`.
  One `zmq.PUB` + one `zmq.SUB` socket, a `zmq-bus-delivery` thread on
  `recv_multipart`. `publish` sends `send_multipart([topic_bytes, wire])`
  (line 139); `subscribe` sets `zmq.SUBSCRIBE` on the first Python sub
  for a topic (wire-level prefix filter, line 147). `SNDHWM`/`RCVHWM`
  default 1000; 50 ms late-joiner settle in `__init__`.
  `DEFAULT_ENDPOINT = "ipc:///tmp/jros-bus.sock"`.
- **ZMQ (chassis)** — `jaeger_os/app/bus/zmq.py` :: `ZmqBus`. PUB→XSUB,
  SUB→XPUB, one delivery thread. Guards concurrent sends with
  `self._pub_lock` (`zmq.py:118`) because ZMQ sockets aren't
  thread-safe and interleaved `send_multipart` calls split frame pairs.
  Wire frame 1 encoded/decoded via the `MessageRegistry` (JSON only).
- **Broker (transport)** — `jaeger_os/transport/broker.py` :: `Broker`
  (XSUB↔XPUB `zmq.proxy` thread, endpoints `ipc:///tmp/jros-xsub.sock`
  / `...-xpub.sock`) + `make_bus_for_node` (env-resolves
  `JAEGER_TRANSPORT_XSUB` / `JAEGER_TRANSPORT_XPUB`, returns a
  `_BrokerZMQBus` that CONNECTs — the split-endpoint ZMQBus variant,
  line 193).
- **Broker (chassis)** — `jaeger_os/app/bus/zmq.py` :: `Broker`.
  Endpoints `tcp://127.0.0.1:7781` (XSUB) / `:7782` (XPUB); env vars
  `JAEGER_BUS_XSUB` / `JAEGER_BUS_XPUB` (`Broker.env()`, line 88).
  Subprocess nodes build their bus in `jaeger_os/app/child.py` ::
  `child_main` → `ZmqBus(registry)` (reads those env vars).
- **Topic schemas** — `jaeger_os/transport/topics.py`. `TopicMessage`
  (`msgspec.Struct`, `kw_only=True`, `forbid_unknown_fields=True`) is
  the common envelope (`topic`, `topic_v`, `t_emit_ns`, `seq`,
  `node_id`, `correlation_id`). Concrete topics inherit it and pin
  `topic` to a `Literal`. Namespaces: `/sense/*` (inputs the brain
  reads), `/act/*` (commands the brain writes). `TOPIC_TO_CLASS`
  registry + `class_for_topic()` (line 562); `ALL_TOPICS`.
- **Codec** — `jaeger_os/transport/codec.py`. `encode`/`decode` pick the
  wire form by topic: `BINARY_TOPICS` (`SENSE_AUDIO_IN`, `ACT_AUDIO_OUT`,
  `SENSE_CAMERA_FRAME`, line 39) ride `msgspec.msgpack` (no base64 hop
  for the `bytes` payloads); everything else rides `msgspec.json`
  (tcpdump-readable). `is_binary_topic()`. `decode_with_topic_sniff`
  is a JSON-only debug helper, not the hot path.
- **Backend selection** — `JaegerApp._build_bus`
  (`jaeger_os/app/app.py:192`): manifest `[bus] backend == "zmq"` →
  start a `Broker` + build a `ZmqBus`; else `InProcBus()`. On the
  brain-runtime side, `jaeger_os/nodes/runtime.py :: get_bus()`
  (line 152) always returns `InProcBus` today (`_bus_factory`,
  line 64).
- **`--mode` flag** — `launch.py:808` (`choices=["monolithic",
  "multiprocess"]`, default `monolithic`). `multiprocess` currently
  prints "not yet operational" and returns 2 (`launch.py:856`);
  monolithic sets `JAEGER_NODE_MODE` and boots in-process.
- **bus → Qt bridge** — `jaeger_os/app/surfaces.py :: make_bus_bridge`
  (line 70): builds a `BusBridge(QObject)` with `message = Signal(object)`;
  subscribes each requested topic, emits the signal from the bus
  callback (Qt marshals it onto the GUI thread), swallows the
  `RuntimeError` when Qt has already deleted the C++ object during quit,
  and `close()` unsubscribes. Callers: avatar_player window / voice_orb,
  avatar_chat, pyside6 tray, rich_tui window (verified via grep).

## request() → ack (tool-RPC, transport stack only)

The `request` primitive backs the "a tool publishes and waits" pattern.
A tool sets `request_msg.correlation_id` (call site fills it), publishes
on an `/act/*` topic, and blocks until a matching `/sense/*` ack carries
the same `correlation_id`. Example wired in the schemas: `SpeechCommand`
on `/act/speech` → `SpokenAck` on `/sense/spoken`
(`topics.py:243`, `topics.py:297`). Timeout default 10 s → returns
`None`. The chassis `app/bus` stack has **no** `request()`.

## Status

- **Done / live:** both `InProcBus` implementations; typed topic schemas
  + JSON/MessagePack codec; `request()` on the transport stack; the
  `make_bus_bridge` bus→Qt hop used by the shipping GUIs; monolithic
  boot (`./launch`).
- **Present but dormant:** both `ZMQBus`/`ZmqBus` + `Broker`
  implementations and `make_bus_for_node` / `child.child_main` exist and
  are importable, but `./launch --mode multiprocess` is **not yet
  operational** (`launch.py:860`) and `runtime.get_bus()` always returns
  `InProcBus`. Node docstrings still flag "monolithic-only coupling"
  pending the multiprocess split (e.g. `jaeger_os/core/audio/session.py:71`,
  `jaeger_os/nodes/audio_session/node.py:11`).
