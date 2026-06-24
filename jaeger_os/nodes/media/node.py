"""MediaNode — ACT_MEDIA → decode → MediaFrame on the bus.

Reuses the live image/gif adapters + our VideoAdapter (custom decoders) to
turn a media file into RGBA FrameBuffers, streamed as ``MediaFrame`` so any
renderer/device shows it. A new ACT_MEDIA preempts the current clip.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any

from jaeger_os.nodes.base import Node
from jaeger_os.nodes.media.decoders import GifAdapter, ImageAdapter, VideoAdapter
from jaeger_os.transport import topics

_GIF = {".gif"}
_VIDEO = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


def media_kind(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in _GIF:
        return "gif"
    if ext in _VIDEO:
        return "video"
    return "image"


class MediaNode(Node):
    """SUB ``/act/media`` → render frames → PUB ``/sense/media_frame`` +
    ``/sense/media_state``. Streaming runs on its own worker thread."""

    def __init__(self, bus: Any, *, width: int = 480, height: int = 360,
                 name: str | None = None) -> None:
        super().__init__(bus=bus, name=name)
        self._w, self._h = width, height
        self._req: "queue.Queue[tuple[str, bool]]" = queue.Queue()
        self._worker: threading.Thread | None = None

    def setup(self) -> None:
        self.bus.subscribe(topics.ACT_MEDIA, self._on_command)
        self._worker = threading.Thread(target=self._run, name="media-stream", daemon=True)
        self._worker.start()

    def teardown(self) -> None:
        try:
            self.bus.unsubscribe(topics.ACT_MEDIA, self._on_command)
        except Exception:  # noqa: BLE001
            pass

    # ── bus ───────────────────────────────────────────────────────
    def _on_command(self, msg: Any) -> None:
        path = getattr(msg, "path", "") or ""
        if path:
            self._req.put((path, bool(getattr(msg, "loop", True))))

    def _adapter_for(self, path: str) -> Any:
        return {"gif": GifAdapter, "video": VideoAdapter}.get(media_kind(path), ImageAdapter)()

    # ── worker ────────────────────────────────────────────────────
    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                path, loop = self._req.get(timeout=0.2)
            except queue.Empty:
                continue
            while not self._req.empty():            # collapse to newest request
                try:
                    path, loop = self._req.get_nowait()
                except queue.Empty:
                    break
            self._play(path, loop)

    def _play(self, path: str, loop: bool) -> None:
        kind = media_kind(path)
        adapter = self._adapter_for(path)
        try:
            adapter.open(path, width=self._w, height=self._h, params={"loop": loop})
        except Exception:  # noqa: BLE001 — a bad file never kills the node
            self.bus.publish(topics.MediaState(path=path, kind=kind, playing=False))
            return
        self.bus.publish(topics.MediaState(path=path, kind=kind, playing=True))
        t0 = time.perf_counter()
        try:
            while not self._stop_event.is_set() and self._req.empty():
                frame = adapter.next_frame(time.perf_counter() - t0)
                if frame is None:
                    break
                self.bus.publish(topics.MediaFrame(
                    data=bytes(frame.data), width=frame.width, height=frame.height))
                if kind == "image":
                    break                            # static — one frame, held by the renderer
                if self._stop_event.wait((frame.duration_ms or 33) / 1000.0):
                    break
        finally:
            try:
                adapter.close()
            except Exception:  # noqa: BLE001
                pass
            self.bus.publish(topics.MediaState(path=path, kind=kind, playing=False))


def make_media_node(bus: Any, config: dict | None = None) -> MediaNode:
    config = config or {}
    return MediaNode(bus, width=int(config.get("width", 480)),
                     height=int(config.get("height", 360)))
