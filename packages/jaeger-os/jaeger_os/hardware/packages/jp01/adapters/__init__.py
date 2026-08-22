"""JP01 controller adapters.

Each adapter implements the matching generic node's adapter Protocol
(``nodes/motor/adapters.MotorAdapter``, ``nodes/light/adapters
.LightAdapter``) over a framework ``Link``, plus the JP01-specific
verbs the capability handlers call and an L1 ``estop()``. Each module
also ships a ``simulator()`` — the firmware-shaped MockTransport
responder that backs ``simulated: true``.
"""

from .avc01 import Avc01LightAdapter
from .mc01 import Mc01MotorAdapter
from .vcc01 import Vcc01VisionAdapter

__all__ = ["Mc01MotorAdapter", "Avc01LightAdapter", "Vcc01VisionAdapter"]
