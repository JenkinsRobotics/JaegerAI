"""node.py — LightNode.

Subscribes to ``/act/light`` (:class:`LightCommand`) and forwards
each command to a :class:`LightAdapter`.  Same shape as
:class:`MotorNode`.
"""

from __future__ import annotations

from jaeger_os.transport import topics
from jaeger_os.nodes.base import Node
from jaeger_os.nodes.light.adapters import LightAdapter
from jaeger_os.transport import Bus


class LightNode(Node):
    """SUB ``/act/light`` → adapter → hardware."""

    def __init__(
        self,
        *,
        bus: Bus,
        adapter: LightAdapter,
        name: str = "light",
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
        self.bus.subscribe(topics.ACT_LIGHT, self._on_light_command)
        self._log(f"subscribed to {topics.ACT_LIGHT}")

    def teardown(self) -> None:
        try:
            self.bus.unsubscribe(topics.ACT_LIGHT, self._on_light_command)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.adapter.stop()
        except Exception as exc:  # noqa: BLE001
            self._log(f"adapter stop error: {type(exc).__name__}: {exc}")

    def _on_light_command(self, msg: topics.TopicMessage) -> None:
        assert isinstance(msg, topics.LightCommand), (
            f"LightNode got unexpected topic: {msg.topic}"
        )
        try:
            self.adapter.send_pattern(
                strip_id=msg.strip_id,
                rgb=list(msg.rgb),
                pattern=msg.pattern,
                duration_ms=msg.duration_ms,
            )
        except Exception as exc:  # noqa: BLE001
            self._log(f"send_pattern error: "
                      f"{type(exc).__name__}: {exc}")
