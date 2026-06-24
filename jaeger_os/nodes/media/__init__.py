"""Media node — our custom media decoders → RGBA frames on the bus.

The node decodes any media file (image/gif via the live adapters, video via
our :class:`~jaeger_os.nodes.media.decoders.VideoAdapter`) into FrameBuffers
and streams them as ``MediaFrame`` on ``/sense/media_frame``. Because it ships
frames (not a Qt-rendered window), the same playback streams to ANY target —
a local player, a robot LED matrix, a remote display node. The decoders live
here so they import cleanly into JROS.
"""

from __future__ import annotations

from jaeger_os.nodes.media.node import MediaNode, make_media_node, media_kind

__all__ = ["MediaNode", "make_media_node", "media_kind"]
