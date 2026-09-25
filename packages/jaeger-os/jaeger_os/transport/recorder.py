"""Recording the bus, and playing it back.

Three questions, one tap point. Everything on the bus is already
encodable, so a recorder is just a subscriber that writes what it
hears — and a replay is just a publisher that reads it.

    blackbox     what happened in the seconds BEFORE the fault
    recording    the whole session, on purpose
    replay       run it again, against the same input

**Blackbox mode** is the one that costs nothing. A bounded ring in
memory, no I/O at all, until a trigger fires — then the whole ring is
written. That is JP01's design (``core/blackbox.py``, spec §7.5),
generalised here so every app gets it rather than one robot. The
insight is worth restating: when an e-stop fires the question is
always *what was it doing just before*, and that is exactly what a log
you started after the fact cannot tell you.

**Replay** is the half nothing in the ecosystem had. A recording is
``(timestamp, topic, encoded_payload)`` — the same bytes the wire
carried — so playing it back publishes messages indistinguishable from
the originals. Feed the audio that broke the STT back into the real
STT, as many times as it takes.

That is deliberately NOT a metrics database. Sampled numbers for
dashboards and trends are a different job with a different shape
(InfluxDB, Prometheus); this is a flight recorder. Both are bus
subscribers, so having one does not block the other.

**What it costs the bus.** Measured at 0.7 µs median on the delivery
thread, against a mic frame that IS 10,000 µs of audio.

The two modes pay differently, on purpose:

* **Blackbox** appends a reference to a bounded deque and returns.
  No encode, no queue, no writer thread, no drops — a ring that does
  no I/O has nothing to hand off TO, and routing it through a queue
  would invent a way to lose messages for no benefit. Encoding happens
  once, at dump time, which is a rare non-realtime event.
* **Continuous** hands off to a writer thread via a bounded queue and
  encodes there.

The hand-off exists for JITTER, not throughput. Encoding is cheap —
msgspec is close to a memcpy, 0.08 ms for a 2.7 MB camera frame — and
a buffered write is 0.001 ms. But a buffered write is only cheap until
the buffer FILLS, and then it is a syscall on the bus delivery thread,
at a moment nobody chose. On the audio path that is a dropout you can
hear. So the disk is never touched from a callback, and the queue is
bounded: a recorder that cannot keep up drops and COUNTS, exactly like
the bus itself, rather than back-pressuring the thing it observes.

**The ring holds message objects, not bytes.** That assumes nobody
mutates a message after publishing it — which the bus already assumes,
since it hands every subscriber the same object.

Format — framed binary, because a recording carries 3.6 MB camera
frames and base64 in JSON would cost a third more for nothing::

    b"JBOX1\\n"
    <json header line>\\n
    repeated:  u64 t_ns | u16 topic_len | topic | u32 len | payload
"""

from __future__ import annotations

import json
import pathlib
import struct
import threading
import time
import queue as _queue
from collections import deque
from typing import Any, Callable, Iterator

from jaeger_os.contract import topics as _topics
from jaeger_os.transport.codec import BINARY_TOPICS, decode, encode

MAGIC = b"JBOX1\n"

#: ~10s of busy traffic. Deliberately small: this is a crash window,
#: not an archive. ROS does not keep one at all — `ros2 bag record` is
#: something you run when you already know there is a problem — so a
#: ring that costs nothing and answers "what happened just before" is
#: already more than the baseline, and making it bigger is a decision
#: an app can take later with evidence.
DEFAULT_CAPACITY = 1000

#: Hand-off depth between the bus and the writer. Deep enough to
#: absorb a disk hiccup, shallow enough that a recorder falling
#: permanently behind sheds instead of eating memory.
QUEUE_DEPTH = 2048

#: How often the writer flushes. A recording that is never flushed
#: loses its tail when the process dies — which is when you most want
#: it — and flushing every message is the syscall storm this design
#: exists to avoid.
FLUSH_EVERY_S = 1.0

_HEAD = struct.Struct("<QHI")      # t_ns, topic_len, payload_len


class Recorder:
    """Subscribe to the bus and keep what it hears.

    ``path=None`` is BLACKBOX mode: a bounded ring, no disk I/O, until
    :meth:`dump` is called. ``path=...`` records continuously.
    """

    def __init__(
        self,
        bus: Any,
        *,
        path: pathlib.Path | str | None = None,
        capacity: int = DEFAULT_CAPACITY,
        prefixes: tuple[str, ...] = ("/",),
        include_binary: bool = False,
        app: str = "",
    ) -> None:
        self.bus = bus
        self.path = pathlib.Path(path) if path else None
        self.app = app
        # Prefix subscriptions, so recording everything is one
        # subscription rather than one per topic — and a recorder that
        # had to enumerate topics would miss any added later.
        self.prefixes = prefixes
        # Binary topics are excluded BY DEFAULT, and the difference is
        # not marginal: measured on 720p30 plus a 16 kHz mic, recording
        # everything is 4.5 GB/hour and skipping the pixels is 3 MB/hour
        # — the same session, 45,000x apart. A recorder you cannot
        # afford to leave running is a recorder that is off when you
        # need it.
        #
        # The list comes from the codec rather than a magic tuple here,
        # so a new binary topic is excluded the day it is added.
        self.include_binary = include_binary
        self._skip = frozenset() if include_binary else frozenset(BINARY_TOPICS)
        self._ring: deque[tuple[int, str, bytes]] = deque(maxlen=capacity)
        self._fh: Any = None
        self._subscribed = False
        # The hand-off. put_nowait from the bus thread, drained by the
        # writer — so nothing on the delivery path can block on I/O.
        self._q: _queue.Queue = _queue.Queue(maxsize=QUEUE_DEPTH)
        self._writer: threading.Thread | None = None
        self._stop = threading.Event()
        self.dropped = 0
        self.recorded = 0

    # ── lifecycle ────────────────────────────────────────────────

    def start(self) -> "Recorder":
        if self._subscribed:
            return self
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Buffered: the writer thread owns the flush cadence, so a
            # big buffer is free rather than a latency risk.
            self._fh = self.path.open("wb", buffering=1 << 20)
            self._write_header(self._fh, "continuous")
        self._stop.clear()
        if self._fh is not None:
            self._writer = threading.Thread(
                target=self._writer_loop, name="recorder", daemon=True)
            self._writer.start()
        for prefix in self.prefixes:
            self.bus.subscribe(prefix, self._on_message)
        self._subscribed = True
        return self

    def stop(self) -> None:
        if self._subscribed:
            for prefix in self.prefixes:
                try:
                    self.bus.unsubscribe(prefix, self._on_message)
                except Exception:  # noqa: BLE001
                    pass
            self._subscribed = False
        # Drain what is already queued before closing, or the tail of
        # the recording is lost on every clean shutdown.
        self._stop.set()
        if self._writer is not None:
            self._writer.join(timeout=3.0)
            self._writer = None
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "Recorder":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # ── the bus side ─────────────────────────────────────────────

    def _on_message(self, msg: Any) -> None:
        """Bus thread. A clock read and a queue put — nothing else.

        Blackbox mode appends to the ring and returns. Continuous mode
        hands off to the writer thread — no encode, no allocation, no
        file descriptor here, because the cost that matters is not
        throughput but the SYSCALL a buffered write makes when its
        buffer fills, at a moment nobody chose. On the audio path that
        is a dropout you can hear.

        A full queue drops, and counts. A recorder must never
        back-pressure the system it observes — the whole point is being
        able to leave it running.
        """
        if self._skip:
            from jaeger_os.contract.paths import canonical
            topic = msg.topic
            if topic in self._skip or canonical(topic) in self._skip:
                return
        if self._fh is None:
            # Blackbox: a deque append with maxlen, which is atomic and
            # ~0.1 µs. Nothing to hand off to — this mode never touches
            # a disk until someone asks for a dump.
            self._ring.append((time.time_ns(), msg))
            self.recorded += 1
            return
        try:
            self._q.put_nowait((time.time_ns(), msg))
        except _queue.Full:
            self.dropped += 1

    def _writer_loop(self) -> None:
        """Encode and write, off the bus threads entirely."""
        last_flush = time.monotonic()
        while True:
            try:
                item = self._q.get(timeout=0.2)
            except _queue.Empty:
                if self._stop.is_set():
                    break
                item = None
            if item is not None:
                t_ns, msg = item
                try:
                    record = (t_ns, msg.topic, encode(msg))
                except Exception:  # noqa: BLE001
                    # A message that will not encode must not take down
                    # the recorder — it is running BECAUSE something is
                    # wrong.
                    self.dropped += 1
                    record = None
                if record is not None:
                    try:
                        self._write_record(self._fh, record)
                        self.recorded += 1
                    except Exception:  # noqa: BLE001
                        self.dropped += 1
            now = time.monotonic()
            if self._fh is not None and now - last_flush >= FLUSH_EVERY_S:
                try:
                    self._fh.flush()
                except Exception:  # noqa: BLE001
                    pass
                last_flush = now
            if self._stop.is_set() and self._q.empty():
                break

    # ── writing ──────────────────────────────────────────────────

    def _write_header(self, fh: Any, mode: str) -> None:
        fh.write(MAGIC)
        fh.write(json.dumps({
            "app": self.app, "mode": mode,
            "created_ns": time.time_ns(),
            "prefixes": list(self.prefixes),
            "include_binary": self.include_binary,
        }).encode("utf-8") + b"\n")

    @staticmethod
    def _write_record(fh: Any, record: tuple[int, str, bytes]) -> None:
        t_ns, topic, wire = record
        raw_topic = topic.encode("utf-8")
        fh.write(_HEAD.pack(t_ns, len(raw_topic), len(wire)))
        fh.write(raw_topic)
        fh.write(wire)

    def dump(self, path: pathlib.Path | str, *, reason: str = "") -> pathlib.Path:
        """Write the ring to disk. The blackbox trigger.

        Never raises: this runs when something has already gone wrong,
        and a recorder that fails while dumping is worse than useless
        because it fails exactly when it is needed.
        """
        out = pathlib.Path(path)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            # deque with maxlen is thread-safe for append/iterate, and
            # a blackbox that took a lock could be blocked by the very
            # writer thread it is trying to snapshot.
            snapshot = list(self._ring)
            with out.open("wb") as fh:
                fh.write(MAGIC)
                fh.write(json.dumps({
                    "app": self.app, "mode": "blackbox", "reason": reason,
                    "created_ns": time.time_ns(), "messages": len(snapshot),
                }).encode("utf-8") + b"\n")
                for t_ns, msg in snapshot:
                    try:
                        self._write_record(fh, (t_ns, msg.topic, encode(msg)))
                    except Exception:  # noqa: BLE001
                        # One unencodable message must not cost the
                        # other 3999.
                        continue
        except Exception:  # noqa: BLE001
            pass
        return out

    def on_trigger(self, topic: str, out_dir: pathlib.Path | str,
                   *, reason: str = "") -> Callable[[Any], None]:
        """Dump whenever ``topic`` fires — an e-stop, a node failure.

        Returns the handler so a caller can unsubscribe it.
        """
        out_dir = pathlib.Path(out_dir)

        def _handler(msg: Any) -> None:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            self.dump(out_dir / f"blackbox-{stamp}.jbox",
                      reason=reason or topic)

        self.bus.subscribe(topic, _handler)
        return _handler


# ── reading it back ──────────────────────────────────────────────

def read(path: pathlib.Path | str) -> Iterator[tuple[int, str, Any]]:
    """Yield ``(t_ns, topic, message)`` from a recording.

    Decoded through the same contract the wire uses, so a recording
    made by an older build fails loudly on a renamed topic rather than
    replaying something subtly wrong.
    """
    p = pathlib.Path(path)
    with p.open("rb") as fh:
        if fh.read(len(MAGIC)) != MAGIC:
            raise ValueError(f"{p}: not a JaegerOS recording")
        fh.readline()                      # header
        while True:
            head = fh.read(_HEAD.size)
            if len(head) < _HEAD.size:
                return                     # clean end, or a truncated
                                           # tail from a killed process
            t_ns, topic_len, payload_len = _HEAD.unpack(head)
            topic = fh.read(topic_len).decode("utf-8")
            payload = fh.read(payload_len)
            if len(payload) < payload_len:
                return
            yield t_ns, topic, decode(payload, topic)


def header(path: pathlib.Path | str) -> dict:
    """The recording's metadata, without reading the body."""
    p = pathlib.Path(path)
    with p.open("rb") as fh:
        if fh.read(len(MAGIC)) != MAGIC:
            raise ValueError(f"{p}: not a JaegerOS recording")
        return json.loads(fh.readline().decode("utf-8"))


def replay(bus: Any, path: pathlib.Path | str, *, speed: float = 1.0,
           prefixes: tuple[str, ...] | None = None) -> int:
    """Publish a recording back onto a bus.

    ``speed`` scales the original gaps: 1.0 is real time, 0 is as fast
    as the bus will take it (right for tests), 0.5 is half speed for
    watching something too quick to see.

    The messages carry their ORIGINAL ``t_emit_ns``, so a consumer
    measuring latency against replayed traffic sees the original
    timings rather than the replay's. That is usually what you want and
    occasionally surprising, so it is worth knowing.
    """
    count = 0
    previous: int | None = None
    for t_ns, topic, msg in read(path):
        if prefixes and not any(topic.startswith(p) for p in prefixes):
            continue
        if speed > 0 and previous is not None:
            gap = (t_ns - previous) / 1e9 / speed
            if gap > 0:
                time.sleep(min(gap, 5.0))   # never stall on a long idle
        previous = t_ns
        bus.publish(msg)
        count += 1
    return count


__all__ = ["Recorder", "read", "replay", "header", "MAGIC",
           "DEFAULT_CAPACITY"]


# ── the common case ──────────────────────────────────────────────

def crash_reports(bus: Any, out_dir: pathlib.Path | str, *,
                  app: str = "", capacity: int = DEFAULT_CAPACITY) -> Recorder:
    """Keep a small window of bus traffic and dump it on a fault.

    The one-liner an app wants:

        recorder = crash_reports(bus, app_dir / ".run" / "crashes")

    Costs a deque append per message and touches the disk never, until
    an e-stop fires. Everything else in this module — continuous
    recording, replay, filtering — is for when you already know what
    you are looking for.
    """
    rec = Recorder(bus, capacity=capacity, app=app).start()
    rec.on_trigger(_topics.ACT_ESTOP_TRIGGER, out_dir, reason="estop")
    return rec


__all__ = __all__ + ["crash_reports"]
