"""A real subprocess node, for proving the zmq backend end to end.

Spawned by ``SubprocessHandle`` as ``python -m
dev.tests.jaeger_os.app._zmq_worker_node``. It finds the broker the only
way a child can — the endpoints its parent put in the environment —
then publishes on a topic the parent is subscribed to.

If this file's heartbeat reaches the parent process, isolated nodes
work: two processes, one bus.
"""

from __future__ import annotations

import os
import time

from jaeger_os.transport import topics
from jaeger_os.transport.broker import make_bus_for_node


def main() -> int:
    node_id = os.environ.get("JAEGER_NODE_ID", "zmq-worker")
    # No endpoints passed explicitly: make_bus_for_node reads
    # JAEGER_TRANSPORT_XSUB / _XPUB from the env the parent set. That is
    # the whole contract between parent and child.
    bus = make_bus_for_node()
    try:
        # The parent may still be attaching its subscriber; publish for a
        # bounded window rather than once, so the test is not a race.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            bus.publish(topics.NodeHealth(
                node=node_id, state="RUNNING",
                detail="hello from a separate process",
            ))
            time.sleep(0.1)
    finally:
        try:
            bus.close()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
