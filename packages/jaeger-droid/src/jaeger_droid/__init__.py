"""jaeger-droid: Droid Mode connecting host gimbal camera, mic & speakers to EmbodimentPort."""

from .host_droid import HostDroidEmbodiment, discover_host_peripherals

__all__ = ["HostDroidEmbodiment", "discover_host_peripherals"]
