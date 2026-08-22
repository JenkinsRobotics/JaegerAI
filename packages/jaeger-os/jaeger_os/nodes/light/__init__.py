"""jaeger_os.nodes.light — LED / lighting controller node package.

Universal interface for LED strip / matrix / panel hardware.
JROS library stays vague: a :class:`LightAdapter` Protocol +
a generic ASCII-line :class:`SerialLightAdapter`.

Specific firmware adapters (JP01-AVC01 Teensy NeoPixel handler,
RGB matrix drivers, WLED HTTP API, etc.) subclass at INSTANCE
level; the library never ships board-specific code.
"""

from .adapters import LightAdapter, SerialLightAdapter
from .node import LightNode

__all__ = ["LightNode", "LightAdapter", "SerialLightAdapter"]
