"""The control plane — ask a RUNNING app things, and tell it to do things.

`BusCatalog` answers "what is running?" but only from *inside* the
process. Nothing outside could inspect a live JaegerOS system or command
it: no CLI, no GUI, no second terminal. Debugging meant adding print
statements and restarting.

Mochi 3.0 had this (``core/host_monitor.py`` + ``tools/monitor_cli.py``
+ ``gui/control_cli.py``) and it is what made a node-based app actually
operable. This is the same idea on JaegerOS's own primitives:

    # in the app
    ControlServer(supervisor=sup, catalog=cat, health=hc, bus=bus).start()

    # from anywhere else
    $ python -m jaeger_os.app.control nodes
    $ python -m jaeger_os.app.control stop animation
    $ python -m jaeger_os.app.control publish /act/display/play '{"adapter":"gif"}'

**Transport.** A ZMQ REP socket, independent of whichever bus backend
the app runs — control has to work on an in-process app too, and an
in-process bus has no endpoint an outsider could reach.

**Security.** The default endpoint is an ``ipc://`` socket under the
user's runtime dir, so filesystem permissions gate access. That matters:
these verbs start and stop nodes and publish arbitrary messages onto the
bus. Binding a ``tcp://`` endpoint hands that to anyone who can reach
the port, so it is never the default and must be asked for explicitly.
"""

from __future__ import annotations

import json
import os
import pathlib
import threading
from typing import Any

import zmq

#: Where the control socket lives when nothing says otherwise. Per-app so
#: two apps on one machine do not collide, and under the user's own
#: directory so the filesystem does the access control.
DEFAULT_SOCKET_DIR = pathlib.Path(
    os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "jaeger"


def default_endpoint(app_name: str = "jaeger") -> str:
    DEFAULT_SOCKET_DIR.mkdir(parents=True, exist_ok=True)
    try:
        # Owner-only: these verbs start and stop nodes and publish onto
        # the bus, so the directory permission IS the access control.
        DEFAULT_SOCKET_DIR.chmod(0o700)
    except OSError:
        pass
    return f"ipc://{DEFAULT_SOCKET_DIR / f'{app_name}.control.sock'}"


class ControlError(Exception):
    """A verb could not be served. Carried back to the caller as text."""


class ControlServer:
    """Serve control requests for a running app.

    Every collaborator is optional: an app with no supervisor still
    answers ``health``; one with no catalog still answers ``ls``. A verb
    whose collaborator is missing returns an error naming what is
    absent, rather than pretending or crashing.
    """

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        app_name: str = "jaeger",
        supervisor: Any = None,
        catalog: Any = None,
        health: Any = None,
        bus: Any = None,
        ctx: zmq.Context | None = None,
    ) -> None:
        self.endpoint = endpoint or default_endpoint(app_name)
        self._supervisor = supervisor
        self._catalog = catalog
        self._health = health
        self._bus = bus
        # Never claim the shared context — see the note in zmq_bus: term()
        # blocks until every socket in a context closes.
        self._ctx = ctx or zmq.Context.instance()
        self._sock: zmq.Socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._started = False

    # ── lifecycle ────────────────────────────────────────────────

    #: Unix domain sockets cap the path at sizeof(sockaddr_un.sun_path),
    #: 104 on macOS and 108 on Linux. A deep XDG_RUNTIME_DIR or a temp
    #: dir can blow past it, and the raw ZMQError names a C struct
    #: rather than the fix.
    IPC_PATH_MAX = 100

    def start(self) -> "ControlServer":
        if self._started:
            return self
        if self.endpoint.startswith("ipc://"):
            path = self.endpoint[len("ipc://"):]
            if len(path) > self.IPC_PATH_MAX:
                raise ControlError(
                    f"control socket path is {len(path)} chars, over the "
                    f"~{self.IPC_PATH_MAX} unix-socket limit: {path}\n"
                    f"Pass a shorter endpoint= or set XDG_RUNTIME_DIR to a "
                    f"shallower directory.")
        self._sock = self._ctx.socket(zmq.REP)
        self._sock.bind(self.endpoint)
        self._thread = threading.Thread(
            target=self._serve, name="jaeger-control", daemon=True)
        self._thread.start()
        self._started = True
        return self

    def stop(self) -> None:
        if not self._started:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._sock is not None:
            try:
                self._sock.close(linger=0)
            except Exception:  # noqa: BLE001
                pass
        # A unix socket outlives the process that bound it. ZMQ binds
        # straight over a stale one, so this is tidiness rather than
        # correctness — but /tmp/jaeger otherwise accumulates a file per
        # app per crash forever, and "what is running" becomes
        # unreadable exactly when someone is debugging a leftover.
        if self.endpoint.startswith("ipc://"):
            try:
                pathlib.Path(self.endpoint[len("ipc://"):]).unlink(
                    missing_ok=True)
            except OSError:
                pass
        self._started = False

    def _serve(self) -> None:
        poller = zmq.Poller()
        poller.register(self._sock, zmq.POLLIN)
        while not self._stop.is_set():
            try:
                if not poller.poll(timeout=200):
                    continue
                raw = self._sock.recv_string()
            except Exception:  # noqa: BLE001 — socket closed under us
                return
            try:
                reply = self.handle(json.loads(raw))
            except Exception as exc:  # noqa: BLE001
                reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            try:
                self._sock.send_string(json.dumps(reply, default=str))
            except Exception:  # noqa: BLE001
                return

    # ── verbs ────────────────────────────────────────────────────

    def handle(self, request: dict) -> dict:
        """Dispatch one request. Exposed directly so tests (and an
        in-process caller) can exercise the verbs without a socket."""
        verb = str(request.get("verb", "")).strip()
        handler = getattr(self, f"_verb_{verb}", None)
        if handler is None:
            return {"ok": False,
                    "error": f"unknown verb {verb!r}",
                    "verbs": self.verbs()}
        try:
            return {"ok": True, "result": handler(request)}
        except ControlError as exc:
            return {"ok": False, "error": str(exc)}

    def verbs(self) -> list[str]:
        return sorted(n[6:] for n in dir(self) if n.startswith("_verb_"))

    def _need(self, obj: Any, name: str) -> Any:
        if obj is None:
            raise ControlError(f"this app has no {name}")
        return obj

    # -- inspect --

    def _verb_ping(self, _req: dict) -> dict:
        return {"pong": True, "endpoint": self.endpoint}

    def _verb_nodes(self, _req: dict) -> dict:
        """Who is running, from the nodes' own announcements."""
        cat = self._need(self._catalog, "bus catalog")
        return {name: {
            "class": m.node_class, "state": m.state, "pid": m.pid,
            "subscribes": list(m.subscribes), "publishes": list(m.publishes),
        } for name, m in cat.nodes().items()}

    def _verb_topics(self, _req: dict) -> dict:
        """Every topic -> its publishers and subscribers."""
        return self._need(self._catalog, "bus catalog").topics()

    def _verb_orphans(self, _req: dict) -> dict:
        """Topics nobody reads, or nobody feeds."""
        return self._need(self._catalog, "bus catalog").orphan_topics()

    def _verb_health(self, _req: dict) -> dict:
        hc = self._need(self._health, "health cache")
        return {
            "system": hc.system_level(),
            "unhealthy": hc.unhealthy(),
            "nodes": {n: {"level": hc.level_for(n),
                          "state": getattr(m, "state", ""),
                          "tick_rate_hz": getattr(m, "tick_rate_hz", 0.0),
                          "tx_rate_hz": getattr(m, "tx_rate_hz", 0.0),
                          "tick_errors": getattr(m, "tick_errors", 0),
                          "uptime_s": round(getattr(m, "uptime_s", 0.0), 1)}
                      for n, m in hc.snapshot().items()},
        }

    def _verb_ls(self, _req: dict) -> list:
        """Declared nodes and their supervised state — including the
        ones that are DISABLED, which never announce and so never appear
        in `nodes`."""
        return self._need(self._supervisor, "supervisor").ls()

    def _verb_diagnose(self, req: dict) -> dict:
        sup = self._need(self._supervisor, "supervisor")
        return sup.diagnose(self._node_arg(req))

    # -- control --

    def _verb_start(self, req: dict) -> dict:
        sup = self._need(self._supervisor, "supervisor")
        node = self._node_arg(req)
        sup.start(node)
        return {"node": node, "running": sup.is_running(node)}

    def _verb_stop(self, req: dict) -> dict:
        sup = self._need(self._supervisor, "supervisor")
        node = self._node_arg(req)
        sup.stop(node)
        return {"node": node, "running": sup.is_running(node)}

    def _verb_restart(self, req: dict) -> dict:
        sup = self._need(self._supervisor, "supervisor")
        node = self._node_arg(req)
        sup.restart(node)
        return {"node": node, "running": sup.is_running(node)}

    def _verb_publish(self, req: dict) -> dict:
        """Put a message on the bus — how an outsider commands a node.

        The payload is validated against the topic's registered contract
        type, so a typo is refused here rather than becoming a malformed
        message some node has to defend against.
        """
        from jaeger_os.transport import topics as _topics

        bus = self._need(self._bus, "bus")
        topic = str(req.get("topic", "")).strip()
        if not topic:
            raise ControlError("publish needs a topic")
        try:
            cls = _topics.class_for_topic(topic)
        except KeyError:
            raise ControlError(
                f"unknown topic {topic!r} — not in the contract") from None
        payload = req.get("payload") or {}
        if not isinstance(payload, dict):
            raise ControlError("payload must be an object")
        try:
            msg = cls(**payload)
        except TypeError as exc:
            raise ControlError(f"payload does not fit {cls.__name__}: {exc}")
        bus.publish(msg)
        return {"topic": topic, "type": cls.__name__}

    @staticmethod
    def _node_arg(req: dict) -> str:
        node = str(req.get("node", "")).strip()
        if not node:
            raise ControlError("this verb needs a node id")
        return node


class ControlClient:
    """Talk to a :class:`ControlServer` from another process."""

    def __init__(self, endpoint: str | None = None, *,
                 app_name: str = "jaeger", timeout_ms: int = 3000,
                 ctx: zmq.Context | None = None) -> None:
        self.endpoint = endpoint or default_endpoint(app_name)
        self._timeout_ms = timeout_ms
        self._ctx = ctx or zmq.Context.instance()

    def request(self, verb: str, **args: Any) -> dict:
        sock = self._ctx.socket(zmq.REQ)
        # Never block forever on a dead app: a REQ socket with no
        # timeout hangs the caller until the process is killed.
        sock.setsockopt(zmq.RCVTIMEO, self._timeout_ms)
        sock.setsockopt(zmq.SNDTIMEO, self._timeout_ms)
        sock.setsockopt(zmq.LINGER, 0)
        try:
            sock.connect(self.endpoint)
            sock.send_string(json.dumps({"verb": verb, **args}))
            return json.loads(sock.recv_string())
        except zmq.Again:
            return {"ok": False,
                    "error": f"no app answered at {self.endpoint}"}
        finally:
            sock.close(linger=0)


def main(argv: list[str] | None = None) -> int:
    """``python -m jaeger_os.app.control <verb> [args]``"""
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m jaeger_os.app.control",
        description="Inspect and control a running JaegerOS app.")
    ap.add_argument("verb", help="ping | nodes | topics | orphans | health | "
                                 "ls | diagnose | start | stop | restart | "
                                 "publish")
    ap.add_argument("target", nargs="?", default="",
                    help="node id, or topic for `publish`")
    ap.add_argument("payload", nargs="?", default="",
                    help="JSON object, for `publish`")
    ap.add_argument("--endpoint", default=None)
    ap.add_argument("--app", default="jaeger", help="app name (socket path)")
    args = ap.parse_args(argv)

    client = ControlClient(args.endpoint, app_name=args.app)
    kwargs: dict[str, Any] = {}
    if args.verb == "publish":
        kwargs["topic"] = args.target
        if args.payload:
            try:
                kwargs["payload"] = json.loads(args.payload)
            except json.JSONDecodeError as exc:
                print(f"payload is not valid JSON: {exc}")
                return 2
    elif args.target:
        kwargs["node"] = args.target

    reply = client.request(args.verb, **kwargs)
    print(json.dumps(reply.get("result", reply), indent=2, default=str))
    return 0 if reply.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ControlServer", "ControlClient", "ControlError",
           "default_endpoint"]
