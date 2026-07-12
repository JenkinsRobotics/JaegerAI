"""Media decoders — asset file -> :class:`FrameBuffer`.

The media node is the asset-handling specialist; these turn any supported
asset (image / gif / video / bitmap / sprite-sheet) into frames. Other nodes
(the animation node today, more later) import + use them over the node tree.
"""

from .bitmap_adapter import BitmapAdapter
from .gif_adapter import GifAdapter
from .image_adapter import ImageAdapter
from .sprite_adapter import SpriteAdapter
from .video_adapter import VideoAdapter

__all__ = [
    "BitmapAdapter", "GifAdapter", "ImageAdapter", "SpriteAdapter", "VideoAdapter",
]
