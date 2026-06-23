"""node.py — MotorNode.

Subscribes to ``/act/motion`` (:class:`MotionCommand`) and
forwards each command to a :class:`MotorAdapter`.

Per-instance hardware adapter (JP01-MC01 ESP32, etc.) plugs in
via the constructor — same shape as TTS/STT/Vision; library has
the universal interface, instance has the hardware specifics.
"""

from __future__ import annotations

from jaeger_os.transport import topics
from jaeger_os.nodes.base import Node
from jaeger_os.nodes.motor.adapters import MotorAdapter
from jaeger_os.transport import Bus


class MotorNode(Node):
    """SUB ``/act/motion`` → adapter → hardware.

    Subscribe callback runs on the Bus delivery thread so we keep
    the dispatch FAST (single adapter call); if your adapter does
    heavy work (waits on board ack, runs PID), push it to its own
    thread inside the adapter rather than blocking the bus
    delivery thread."""

    def __init__(
        self,
        *,
        bus: Bus,
        adapter: MotorAdapter,
        name: str = "motor",
        install_signal_handlers: bool = False,
    ) -> None:
        super().__init__(
            bus=bus,
            name=name,
            install_signal_handlers=install_signal_handlers,
        )
        self.adapter = adapter

    def setup(self) -> None:
        self.adapter.start()
        self.bus.subscribe(topics.ACT_MOTION, self._on_motion_command)
        self._log(f"subscribed to {topics.ACT_MOTION}")

    def teardown(self) -> None:
        try:
            self.bus.unsubscribe(topics.ACT_MOTION, self._on_motion_command)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.adapter.stop()
        except Exception as exc:  # noqa: BLE001
            self._log(f"adapter stop error: {type(exc).__name__}: {exc}")

    def _on_motion_command(self, msg: topics.TopicMessage) -> None:
        assert isinstance(msg, topics.MotionCommand), (
            f"MotorNode got unexpected topic: {msg.topic}"
        )
        if msg.use_waypoint:
            try:
                self.adapter.send_waypoint(target_xy=list(msg.target_xy))
            except Exception as exc:  # noqa: BLE001
                self._log(f"send_waypoint error: "
                          f"{type(exc).__name__}: {exc}")
            return
        try:
            self.adapter.send_velocity(
                linear_x_mps=msg.linear_x_mps,
                linear_y_mps=msg.linear_y_mps,
                angular_z_rps=msg.angular_z_rps,
                duration_s=msg.duration_s,
            )
        except Exception as exc:  # noqa: BLE001
            self._log(f"send_velocity error: "
                      f"{type(exc).__name__}: {exc}")
