"""jaeger-droid: Droid Mode connecting host gimbal camera, mic & speakers to EmbodimentPort."""

from .host_droid import HostDroidEmbodiment, discover_host_peripherals
from .reflex import DroidReflexController

__all__ = ["DroidReflexController", "HostDroidEmbodiment", "discover_host_peripherals"]
