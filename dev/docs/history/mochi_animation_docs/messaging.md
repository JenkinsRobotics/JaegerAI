# Mochi Messaging Topology

This document summarises the ZeroMQ addresses and topic namespaces shared across the Mochi host, plugins, and GUI tools.

## Addresses

The host reads `config.yaml` and launches a broker plus the animation node. Key addresses:

- **Broker frontend (`broker.frontend_addr`)** – XPUB side, all subscribers connect here.
- **Broker backend (`broker.backend_addr`)** – XSUB side, all publishers connect here.
- **Control (`node.ctrl_address`)** – PUSH/PULL channel for textual commands.

The host propagates the chosen addresses to plugins via environment variables so they do not need to hard-code ports. Control messages can be targeted to a specific node by prefixing commands with `node <id>`, for example `node animation mode on solid_color`.

## Topic Naming

Topics are UTF-8 strings with dotted sections. Helper utilities live in `transport/topics.py`.

```
sys.<area>.<name>        # host/broker signals
node.<id>.<signal>       # required per-node topics
ext.<feature>.<signal>   # optional cross-node channels
```

The host monitor subscribes to `node.*` topics and exposes the latest health/meta/event state over a REP socket (see `monitor.rep_address` in `config.yaml`). Clients can issue `GET health`, `GET meta`, or `GET event <node_id>` requests to retrieve cached data without maintaining their own subscriptions.

### Required Topics (`node.<id>.*`)

Every node advertises the following bundle via `make_node_topics(node_id)`:

- `node.<id>.frame`   – binary frame packets (`pack_frame` format).
- `node.<id>.health`  – JSON heartbeat (`mochi.node.health.v1`).
- `node.<id>.event`   – JSON event stream (`mochi.node.event.v1`).
- `node.<id>.meta`    – JSON capabilities announcement (`mochi.node.meta.v1`).

The animation node publishes a `meta` message when it boots, listing these required topics and any optional ones. GUI tools listen to `health` for status and may listen to `event` for richer telemetry.

### Optional Topics (`ext.*`)

Optional or feature-specific channels live under the `ext.` namespace. Common placeholders exported today:

- `ext.stt.text`
- `ext.llm.reply`

Standard shared topics defined in `transport/messages.py` include `stt.text`, `llm.reply`, `tts.say`, `tts.done`, `anim.event`, and `system.cmd`. Plugins can declare optional topics in configuration (`node.optional_topics`) or via the `MOCHI_NODE_OPTIONAL_TOPICS` environment variable. They are surfaced in the meta payload for discovery.

## Payload Shapes

- **Frame:** binary header (`>HHQI`) followed by packed RGB data.
- **Health:**

```
{
  "schema": "mochi.node.health.v1",
  "node_id": "animation",
  "timestamp_ms": 1700000000000,
  "sequence": 42,
  "logical_size": {"width": 64, "height": 64},
  "fps_target": 60,
  "mode": "solid_color",
  "memory_mb": 123.4,
  "tx_rate_mbps": 2.5
}
```

- **Event:**

```
{
  "schema": "mochi.node.event.v1",
  "node_id": "animation",
  "timestamp_ms": 1700000000100,
  "event": "mode.changed",
  "data": {"mode": "solid_color", "source": "ctrl"}
}
```

- **Meta:** Produced via `describe_node_catalog(...)`, including addresses, logical size, FPS, and optional topics.

Cross-service messages (e.g., STT → LLM → TTS) use the shared `Msg` envelope defined in `transport/messages.py`:

```
{
  "id": "f0ad...",
  "ts": 1700000000.1,
  "source": "llm",
  "kind": "assistant",
  "text": "Hello there!",
  "meta": {"in_reply_to": "..."}
}
```

## Using the Helpers

```python
from core import make_node_topics

node_topics = make_node_topics("animation")
sub.setsockopt(zmq.SUBSCRIBE, node_topics.health)
```

The same helpers are used by the host (to configure plugins), the animation node (to publish), and GUI tools (to subscribe).
