"""The control plane — inspect and command a running app from outside.

`BusCatalog` answers "what is running?" but only from INSIDE the
process. Nothing external could inspect a live JaegerOS system or
command it — no CLI, no GUI, no second terminal. Debugging meant adding
prints and restarting.

Mochi 3.0 had exactly this (host_monitor + monitor_cli + control_cli)
and it is what made a node-based app operable rather than merely
runnable.
"""

from __future__ import annotations

import os
import pathlib
import threading
import time

import pytest

from jaeger_os.app.catalog import BusCatalog
from jaeger_os.app.control import (
    ControlClient, ControlError, ControlServer, default_endpoint,
)
from jaeger_os.app.health import HealthCache
from jaeger_os.nodes.base import Node
from jaeger_os.transport import InProcBus, topics

pytestmark = pytest.mark.integration


class _Face(Node):
    def setup(self):
        self.received = []
        self.subscribe(topics.ACT_DISPLAY_PLAY, self.received.append)

    def tick(self):
        self.publish(topics.DisplayState(
            state="idle", progress=1.0, elapsed_ms=0))
        time.sleep(0.02)


class _FakeSupervisor:
    """Just enough supervisor to exercise the control verbs."""

    def __init__(self):
        self.running = {"animation": True, "tts": False}

    def start(self, node_id):
        if node_id not in self.running:
            raise KeyError(node_id)
        self.running[node_id] = True

    def stop(self, node_id):
        if node_id not in self.running:
            raise KeyError(node_id)
        self.running[node_id] = False

    def restart(self, node_id):
        self.stop(node_id)
        self.start(node_id)

    def is_running(self, node_id):
        return self.running.get(node_id, False)

    def ls(self):
        return [{"id": n, "running": r} for n, r in self.running.items()]

    def diagnose(self, node_id):
        return {"id": node_id, "running": self.is_running(node_id)}


@pytest.fixture
def sock_dir():
    """Unix sockets cap the path around 100 chars and pytest's tmp_path
    is already longer than that on macOS."""
    import shutil
    import tempfile
    d = tempfile.mkdtemp(prefix="/tmp/jt-")
    yield pathlib.Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def system(sock_dir):
    """A running app-ish system with a control server on its own socket."""
    bus = InProcBus()
    catalog = BusCatalog(bus).attach()
    health = HealthCache(bus)
    node = _Face(bus=bus, name="animation", install_signal_handlers=False)
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    time.sleep(0.5)
    endpoint = f"ipc://{sock_dir}/control.sock"
    sup = _FakeSupervisor()
    server = ControlServer(endpoint=endpoint, catalog=catalog, health=health,
                           bus=bus, supervisor=sup).start()
    yield {"bus": bus, "node": node, "server": server, "supervisor": sup,
           "client": ControlClient(endpoint), "catalog": catalog}
    server.stop()
    node.stop()
    thread.join(timeout=2)
    bus.close()


# ── it answers from another socket ───────────────────────────────

def test_ping_reaches_a_running_app(system):
    reply = system["client"].request("ping")
    assert reply["ok"] and reply["result"]["pong"]


def test_nodes_lists_what_is_running(system):
    reply = system["client"].request("nodes")
    assert reply["ok"]
    assert "animation" in reply["result"]
    assert reply["result"]["animation"]["class"] == "_Face"


def test_health_reports_severity_and_rates(system):
    time.sleep(1.2)   # let a heartbeat land
    reply = system["client"].request("health")
    assert reply["ok"]
    assert reply["result"]["system"] in topics.HEALTH_LEVELS


def test_topics_and_orphans_are_queryable(system):
    system["catalog"].request_announce()
    time.sleep(0.3)
    assert system["client"].request("topics")["ok"]
    assert system["client"].request("orphans")["ok"]


# ── it can COMMAND, not just observe ─────────────────────────────

def test_publish_delivers_a_command_from_outside_the_process(system):
    """The whole point: an external tool tells a node to do something."""
    reply = system["client"].request(
        "publish", topic=topics.ACT_DISPLAY_PLAY,
        payload={"adapter": "gif", "asset_path": "x.gif"})
    assert reply["ok"], reply
    deadline = time.monotonic() + 3.0
    while not system["node"].received and time.monotonic() < deadline:
        time.sleep(0.02)
    assert system["node"].received, "the node never got the command"
    assert system["node"].received[0].adapter == "gif"


def test_publish_validates_against_the_contract(system):
    """A typo is refused here rather than becoming a malformed message
    some node has to defend against."""
    reply = system["client"].request(
        "publish", topic=topics.ACT_DISPLAY_PLAY, payload={"nope": 1})
    assert not reply["ok"]
    assert "DisplayCommand" in reply["error"]


def test_publish_refuses_a_topic_outside_the_contract(system):
    reply = system["client"].request("publish", topic="/act/invented")
    assert not reply["ok"]
    assert "not in the contract" in reply["error"]


# ── failure modes a caller will actually hit ─────────────────────

def test_an_unknown_verb_lists_the_real_ones(system):
    reply = system["client"].request("frobnicate")
    assert not reply["ok"]
    assert "nodes" in reply["verbs"]


def test_a_verb_needing_an_absent_collaborator_says_so(sock_dir):
    """An app without a supervisor must explain that, not crash or
    silently no-op."""
    server = ControlServer(endpoint=f"ipc://{sock_dir}/bare.sock")
    out = server.handle({"verb": "start", "node": "animation"})
    assert not out["ok"]
    assert "supervisor" in out["error"]


def test_a_verb_needing_a_node_id_says_so(system):
    out = system["server"].handle({"verb": "diagnose"})
    assert not out["ok"] and "node id" in out["error"]


# ── turning nodes on and off from outside ────────────────────────

def test_stop_and_start_a_node(system):
    """What a ROS-style harness is for: toggle a node without touching
    the app's code or restarting it."""
    client, sup = system["client"], system["supervisor"]
    assert sup.is_running("animation")

    reply = client.request("stop", node="animation")
    assert reply["ok"] and reply["result"]["running"] is False
    assert not sup.is_running("animation")

    reply = client.request("start", node="animation")
    assert reply["ok"] and reply["result"]["running"] is True


def test_restart_a_node(system):
    reply = system["client"].request("restart", node="animation")
    assert reply["ok"] and reply["result"]["running"] is True


def test_ls_shows_disabled_nodes_too(system):
    """A disabled node never announces, so it is absent from `nodes` —
    `ls` is how you see it exists at all."""
    reply = system["client"].request("ls")
    assert reply["ok"]
    ids = {row["id"] for row in reply["result"]}
    assert "tts" in ids, "a declared-but-stopped node vanished"


def test_diagnose_a_node(system):
    reply = system["client"].request("diagnose", node="tts")
    assert reply["ok"] and reply["result"]["id"] == "tts"


def test_commanding_an_unknown_node_is_an_error_not_a_crash(system):
    reply = system["client"].request("stop", node="ghost")
    assert not reply["ok"]
    assert "ghost" in reply["error"]


def test_a_client_does_not_hang_on_a_dead_app(sock_dir):
    """A REQ socket with no timeout hangs the caller until the process
    is killed — unacceptable for a CLI."""
    client = ControlClient(f"ipc://{sock_dir}/nobody.sock", timeout_ms=300)
    t0 = time.monotonic()
    reply = client.request("ping")
    assert not reply["ok"]
    assert "no app answered" in reply["error"]
    assert time.monotonic() - t0 < 3.0


# ── security-relevant defaults ───────────────────────────────────

def test_the_default_endpoint_is_ipc_not_tcp():
    """These verbs start/stop nodes and publish onto the bus. A tcp
    default would hand that to anyone who can reach the port."""
    assert default_endpoint("x").startswith("ipc://")


def test_the_socket_directory_is_owner_only():
    import pathlib
    import stat

    from jaeger_os.app.control import DEFAULT_SOCKET_DIR

    default_endpoint("perm-check")
    mode = stat.S_IMODE(pathlib.Path(DEFAULT_SOCKET_DIR).stat().st_mode)
    assert mode & 0o077 == 0, f"world/group accessible: {oct(mode)}"


def test_apps_get_separate_sockets():
    assert default_endpoint("alpha") != default_endpoint("beta")


# ── the app wires it up ──────────────────────────────────────────

def test_an_app_exposes_a_control_plane_by_default(tmp_path):
    from jaeger_os.app.app import JaegerApp

    (tmp_path / "jaeger.toml").write_text(
        '[app]\nname = "ctltest"\nrequires_framework = ">=0.1"\n'
        'mode = "fused"\nevent_loop = "none"\nconfig = ""\n'
        '\n[bus]\nbackend = "inproc"\n')
    app = JaegerApp(tmp_path / "jaeger.toml")
    try:
        app.boot()
        assert app._control is not None
        assert ControlClient(app_name="ctltest").request("ping")["ok"]
    finally:
        app.shutdown()


def test_an_app_can_turn_the_control_plane_off(tmp_path):
    from jaeger_os.app.app import JaegerApp

    (tmp_path / "jaeger.toml").write_text(
        '[app]\nname = "noctl"\nrequires_framework = ">=0.1"\n'
        'mode = "fused"\nevent_loop = "none"\nconfig = ""\n'
        'control = false\n\n[bus]\nbackend = "inproc"\n')
    app = JaegerApp(tmp_path / "jaeger.toml")
    try:
        app.boot()
        assert app._control is None
    finally:
        app.shutdown()


def test_an_overlong_socket_path_explains_itself():
    """The raw ZMQError names a C struct field, not the fix."""
    long_path = "/tmp/" + ("x" * 120) + "/control.sock"
    with pytest.raises(ControlError) as exc:
        ControlServer(endpoint=f"ipc://{long_path}").start()
    assert "unix-socket limit" in str(exc.value)


# ── shutdown leaves nothing behind ───────────────────────────────

@pytest.fixture
def short_sock():
    """A socket path SHORT enough to bind.

    Not tmp_path: pytest's is ~140 chars and unix sockets cap the path
    at ~104, so ControlServer rejects it — correctly, which is how this
    fixture came to exist.
    """
    made = []

    def make(name):
        path = pathlib.Path(f"/tmp/jaeger-test-{name}-{os.getpid()}.sock")
        made.append(path)
        return f"ipc://{path}"

    yield make
    for path in made:
        path.unlink(missing_ok=True)


def test_stop_unlinks_the_socket_file(short_sock):
    """A unix socket outlives the process that bound it.

    ZMQ binds straight over a stale one, so this is tidiness rather
    than correctness — but without it /tmp/jaeger accumulates a file
    per app per crash forever, and 'what is running' becomes
    unreadable exactly when someone is debugging a leftover.
    """
    endpoint = short_sock("unlink")
    path = pathlib.Path(endpoint[len("ipc://"):])

    server = ControlServer(endpoint=endpoint, catalog=None,
                           health=None, bus=None).start()
    assert path.exists(), "never bound"
    server.stop()
    assert not path.exists(), "socket file left behind after stop()"


def test_stop_is_idempotent_and_survives_a_missing_file(short_sock):
    """Shutdown must never raise — a second stop(), or someone having
    already cleaned /tmp, is not an error."""
    endpoint = short_sock("idem")
    server = ControlServer(endpoint=endpoint, catalog=None,
                           health=None, bus=None).start()
    pathlib.Path(endpoint[len("ipc://"):]).unlink()
    server.stop()
    server.stop()


def test_app_shutdown_stops_the_control_plane(tmp_path):
    """The real leak: JaegerApp.shutdown() never stopped the control
    server at all. The thread is a daemon so the process still exited,
    which is why this went unnoticed — the evidence was a socket file
    per run, not a hung app."""
    from jaeger_os.app import JaegerApp

    (tmp_path / "jaeger.toml").write_text(
        '[app]\nname = "ctl-shutdown-test"\n'
        'requires_framework = ">=0.1"\nmode = "fused"\n'
        'event_loop = "none"\nconfig = ""\ncontrol = true\n'
        '\n[bus]\nbackend = "inproc"\n')

    app = JaegerApp(tmp_path / "jaeger.toml")
    app.boot()
    sock = pathlib.Path(
        default_endpoint("ctl-shutdown-test")[len("ipc://"):])
    assert sock.exists(), "control plane never came up"
    app.shutdown()
    assert not sock.exists(), "control socket survived app.shutdown()"


def test_a_crashed_run_leaves_nothing_for_the_next_boot(tmp_path):
    """SIGKILL cannot unlink anything — no process runs code after it.

    So the NEXT boot cleans up, at the one moment it is provably safe:
    the previous pid has just been checked and found dead. Doing this
    in ControlServer.start() instead would delete a LIVE peer's socket
    and silently steal its endpoint.
    """
    from jaeger_os.app import JaegerApp

    (tmp_path / "jaeger.toml").write_text(
        '[app]\nname = "crash-reap-test"\n'
        'requires_framework = ">=0.1"\nmode = "fused"\n'
        'event_loop = "none"\nconfig = ""\ncontrol = true\n'
        '\n[bus]\nbackend = "inproc"\n')

    sock = pathlib.Path(default_endpoint("crash-reap-test")[len("ipc://"):])
    sock.parent.mkdir(parents=True, exist_ok=True)

    # Forge the wreckage of a killed run: a slot naming a dead pid, and
    # the socket file it never got to remove.
    #
    # The slot lives at <project>/.run/<name>.pid — NOT beside the
    # socket. Getting that wrong makes this test pass without ever
    # entering the stale branch, which is exactly what it did on the
    # first attempt: boot() simply found no slot and the reap never ran.
    run_dir = tmp_path / ".run"
    run_dir.mkdir(parents=True, exist_ok=True)
    slot = run_dir / "crash-reap-test.pid"
    slot.write_text("999999")           # a pid that cannot be alive
    # An earlier run of THIS test can leave a real socket here, and
    # write_text() on a socket raises OSError 102 — so clear the path
    # before forging wreckage on it.
    sock.unlink(missing_ok=True)
    sock.write_text("not a real socket")
    stale_inode = sock.stat().st_ino

    app = JaegerApp(tmp_path / "jaeger.toml")
    try:
        app.boot()                       # must not raise SecondInstance
        assert sock.exists(), "the new run's own socket should be bound"
        # The proof the reap ran: this is a NEW socket, not the forged
        # regular file left by the dead run.
        assert sock.stat().st_ino != stale_inode, "the stale file survived"
        assert slot.read_text().strip() == str(os.getpid())
    finally:
        app.shutdown()
        slot.unlink(missing_ok=True)
    assert not sock.exists()
