# Concept examples

ROS-style demo-driven contract hardening: each example below is a
**doc, not working code** — a concept mapping of a real or archetypal
app onto `TAXONOMY.md`'s five tiers, honest about what already exists
in the Jaeger ecosystem versus what would need building. The point
isn't to ship these apps; it's to find, before 1.0, exactly where the
current module/topic/capability contract bends or breaks under a
demo a real roboticist would recognize — the same role ROS's own
canonical demos (turtlesim, the nav2 stack, MoveIt) play for ROS
itself.

Every gap an example finds gets pulled into `FRAMEWORK_GAPS.md` — that
file, not any individual example, is the actionable 1.0 TODO list.

## The six examples

| Example | Verdict |
|---|---|
| [`simple_tts_app.md`](simple_tts_app.md) | **all exists ✓** — kokoro standalone, the trivial floor case |
| [`simple_chatbot.md`](simple_chatbot.md) | **exists ✓ as config** — mind + chat face, no voice; the "mind is a MODULE" framing is (planned) |
| [`two_axis_turret.md`](two_axis_turret.md) | **mostly exists ✓** — JP01's own head pattern; gap is a generalized joint contract |
| [`lidar_map.md`](lidar_map.md) | **needs building** — the classic ROS demo; stresses the transport/topic-vocabulary claims hardest |
| [`six_axis_arm.md`](six_axis_arm.md) | **needs building** — stresses motion safety + trajectory semantics at scale |
| [`jp01.md`](jp01.md) | **the real one, as reference** — most of it exists today; the JP01 pass (contract adoption, out-of-tree loading, capability-layer gap closures, unit handshake) is designed, not yet shipped |

## Reading order

If you're new to the ecosystem, read them in table order — each one
adds one more tier or one more gap class on top of the last:
`simple_tts_app` (module only) → `simple_chatbot` (+ distribution) →
`two_axis_turret` (+ workspace, JP01-shaped) → `lidar_map` (+ new
topics, new slot) → `six_axis_arm` (+ trajectory/safety-envelope
gaps) → `jp01` (the real body all five hypotheticals are checked
against).

See [`../TAXONOMY.md`](../TAXONOMY.md) for the tier definitions these
examples are mapped onto, and [`FRAMEWORK_GAPS.md`](FRAMEWORK_GAPS.md)
for the consolidated, tagged gap list.
