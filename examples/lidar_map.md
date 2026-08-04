# Example — LiDAR + mapping (the classic ROS demo)

**Verdict: needs building — the example that stresses the transport
claims. Lidar driver module is NEW (new slot), SLAM/mapping node is
NEW, and the scan/map/pose topic TYPES don't exist yet.**

The textbook ROS bring-up: a spinning (or solid-state) lidar publishes
range scans, a SLAM node consumes them plus odometry and produces a
map + a pose estimate, a viewer shows both. Chosen deliberately because
it's the demo every roboticist already has a mental model for — any
gap that shows up here is a gap in "is JaegerOS actually a robotics
framework" in the most literal sense.

## Tiers used

MODULE (lidar driver, new slot) + MODULE (SLAM/mapping, new module,
mind-independent) + PACKAGE/WORKSPACE (the body owning the lidar
controller) + APP (Studio panel or a chat face rendering the map).

## Modules required

| Module | Status | Slot | Notes |
|---|---|---|---|
| Lidar driver | **NEW** | `ranging` (**NEW slot** — no existing slot fits; `vision` is camera-shaped, not range-shaped) | `module.yaml` sketch below. |
| SLAM/mapping node | **NEW module** | none (not a slot-bound engine module — more likely a `jaeger_os.nodes`-shaped compute node subscribing to scan + proprio, independent of the mind) | Consumes `/sense/scan` + `/sense/proprio`, produces `/sense/map` (and, arguably, a pose topic — see gaps). |
| Viz | **EXISTS ✓, shape only** | — | Studio already has the panel-rendering pattern (trace view, health); a map-view panel would follow the same "subscribe to a bus topic, render it" shape Studio already uses — no new framework mechanism, just a new panel. |

Lidar driver `module.yaml` sketch (**NEW** — nothing like this exists
today):

```yaml
module: rplidar_a1          # or whatever the real sensor is
slot: ranging                # NEW slot — proposed
version: 0.1.0
consumes: []
produces: [/sense/scan]       # NEW topic — see below
tools: []                     # a sensor driver typically registers no tools
factory: rplidar_a1:make_ranging_node
config: rplidar_a1
requires_libraries: [rplidar]  # whatever the real driver package is
```

## Topics

| Topic | Status | Notes |
|---|---|---|
| `/sense/scan` | **NEW — needed** | A lidar scan: angle range, per-beam ranges (or a point cloud), timestamp, frame reference. Nothing in `jaeger_os/contract/topics.py` today carries range data — `ProprioReading` is joint encoders/IMU, `CameraFrame` is pixels, neither fits. |
| `/sense/map` | **NEW — needed** | The SLAM node's output: an occupancy grid or equivalent, at whatever rate the mapping algorithm updates it (not necessarily per-scan). |
| a pose topic (`/sense/pose`?) | **NEW — needed, currently absent even in concept** | SLAM conventionally also emits "where am I in the map" separately from the map itself (ROS: `/tf`, `map`→`odom`→`base_link`). JaegerOS's existing `ProprioReading` is body-frame (joint/IMU), not world-frame — there is no existing topic for "estimated pose in a map," and no frame/transform concept at all in the contract today. |
| `/sense/proprio` (consumed, not new) | **EXISTS ✓** | Already multi-field (`joints_rad`, `imu_quat`, `imu_omega`) — usable as odometry input to SLAM as-is, at least for a wheeled/IMU body. |

## Capability declarations

None strictly required — a lidar is a pure sensor (`READ_ONLY`
territory only), so if it's exposed as a capability at all (rather
than staying pure bus traffic with no agent-facing tool), it would be
a single `READ_ONLY` capability like JP01's `robot_vision.stream_info`
— "here's the stream endpoint," not an action. The interesting
capability-layer question this example raises isn't permission tiers
(lidar has none of JP01's HARDWARE-tier danger) — it's the topic and
rate story below.

## App/workspace shape

WORKSPACE for the body (topology.yaml declaring the lidar controller,
same shape as any other sensor controller), plus a compute-only
module (the SLAM node) that isn't hardware-package-bound at all — it's
a pure bus consumer/producer, closer to the `media` module's shape
(engine module, no hardware controller) than to `jp01`'s.

## Framework gaps exposed (the actionable ones)

1. **No scan/map/pose topic types exist.** Three new
   `msgspec.Struct` schemas need adding to `jaeger_os/contract/topics.py`
   before this example can even be stubbed out, let alone implemented.
2. **No high-rate binary-topic convention beyond "use MessagePack."**
   `CameraFrame`/`AudioInFrame` establish the pattern (binary payload,
   MessagePack encoding, no base64 hop) but a lidar scan at a real
   sensor's native rate (5-20 Hz, thousands of points) hasn't been
   tested against the bus's actual throughput — there's no documented
   rate budget or backpressure story anywhere in `contract/`.
3. **No QoS story at all.** `TopicMessage`'s envelope
   (`topic`, `topic_v`, `t_emit_ns`, `seq`, `node_id`, `correlation_id`)
   has no reliability, ordering, or "drop old frames under load"
   semantics — every topic today is implicitly "best effort, whatever
   the bus backend does." A map topic (low-rate, must-not-drop) and a
   raw scan topic (high-rate, fine-to-drop-and-replace) have
   genuinely different delivery needs that the contract doesn't
   distinguish between. This is the honest, unglamorous gap: JaegerOS's
   transport claims ("the bus" as a uniform pub/sub layer) haven't
   been stress-tested against a workload where "keep every message"
   and "keep only the newest" both need to coexist.
4. **No frame/transform concept.** A pose estimate is meaningless
   without a coordinate-frame convention (ROS's `tf` tree). JaegerOS
   has never needed one because no existing topic requires reasoning
   about "position in a shared map" — this example is the first to.
