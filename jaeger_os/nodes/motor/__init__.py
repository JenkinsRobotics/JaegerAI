"""jaeger_os.nodes.motor — motion controller node package.

Universal interface for motor / motion-control hardware.  JROS
library stays vague: a :class:`MotorAdapter` Protocol + a
generic :class:`SerialMotorAdapter` for any board that speaks a
simple ASCII line protocol over USB-CDC or TCP.

Hardware-specific wire formats land at INSTANCE level when the
operator wires their actual robot — JP01-MC01 (ESP32) today,
something else tomorrow.  This package doesn't ship board-specific
code.

The node subscribes to :data:`jaeger_os.transport.topics.ACT_MOTION`
(:class:`MotionCommand`) and forwards each command to the adapter.
Future work (Track D / per-instance): proprio feedback published
on :data:`jaeger_os.transport.topics.SENSE_PROPRIO`.
"""

from .adapters import MotorAdapter, SerialMotorAdapter
from .node import MotorNode

__all__ = ["MotorNode", "MotorAdapter", "SerialMotorAdapter"]
