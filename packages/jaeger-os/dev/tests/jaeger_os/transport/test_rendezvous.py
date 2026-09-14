"""Finding a running app's bus, on this machine.

A subprocess node is told where the bus is by its parent. Anything the
app did NOT spawn had no way to find it — this closes that, the same
way the control plane already did for its own socket.

Local only, deliberately. These tests assert that too: nothing here
should ever listen on a network interface, because the bus carries
motor commands and opening it to whoever can reach a port is a
different feature with a different threat model.
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from jaeger_os.transport import rendezvous


@pytest.fixture(autouse=True)
def clean():
    for name in ("rz-test", "rz-other", "rz-stale"):
        rendezvous.withdraw(name)
    yield
    for name in ("rz-test", "rz-other", "rz-stale"):
        rendezvous.withdraw(name)


# ── publish / find ───────────────────────────────────────────────

def test_a_running_app_can_be_found():
    rendezvous.publish("rz-test", xsub="tcp://127.0.0.1:7770",
                       xpub="tcp://127.0.0.1:7771")
    found = rendezvous.find("rz-test")
    assert found["xsub"] == "tcp://127.0.0.1:7770"
    assert found["xpub"] == "tcp://127.0.0.1:7771"
    assert found["pid"] == os.getpid()


def test_an_app_that_is_not_running_is_not_found():
    assert rendezvous.find("rz-test") is None


def test_withdraw_is_idempotent():
    rendezvous.publish("rz-test", xsub="tcp://a", xpub="tcp://b")
    rendezvous.withdraw("rz-test")
    rendezvous.withdraw("rz-test")
    assert rendezvous.find("rz-test") is None


def test_apps_do_not_collide():
    rendezvous.publish("rz-test", xsub="tcp://a1", xpub="tcp://b1")
    rendezvous.publish("rz-other", xsub="tcp://a2", xpub="tcp://b2")
    assert rendezvous.find("rz-test")["xsub"] == "tcp://a1"
    assert rendezvous.find("rz-other")["xsub"] == "tcp://a2"


# ── the failure that matters: a crashed app ──────────────────────

def test_a_record_from_a_dead_process_is_not_returned():
    """A crash leaves the file behind. Handing it back means every
    future connect targets a port nobody is bound to — which fails as
    SILENCE, not an error, because a ZMQ connect to nothing succeeds."""
    path = rendezvous.rendezvous_path("rz-stale")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "app": "rz-stale", "pid": 999_999,      # nothing is this pid
        "xsub": "tcp://127.0.0.1:7772", "xpub": "tcp://127.0.0.1:7773",
    }))
    assert rendezvous.find("rz-stale") is None


def test_a_stale_record_is_cleaned_up_not_just_ignored():
    path = rendezvous.rendezvous_path("rz-stale")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"app": "rz-stale", "pid": 999_999,
                                "xsub": "tcp://a", "xpub": "tcp://b"}))
    rendezvous.find("rz-stale")
    assert not path.exists(), "a dead app's file lingers forever"


def test_a_corrupt_record_is_absent_not_an_exception():
    path = rendezvous.rendezvous_path("rz-test")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json")
    assert rendezvous.find("rz-test") is None


def test_a_record_missing_endpoints_is_absent():
    path = rendezvous.rendezvous_path("rz-test")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"app": "rz-test", "pid": os.getpid()}))
    assert rendezvous.find("rz-test") is None


def test_the_write_is_atomic():
    """A reader must never see half a document — a torn read hands
    someone a truncated endpoint and a connection that goes nowhere."""
    rendezvous.publish("rz-test", xsub="tcp://a", xpub="tcp://b")
    leftovers = list(rendezvous.rendezvous_path("rz-test").parent
                     .glob("*.json.tmp"))
    assert leftovers == [], f"temp file left behind: {leftovers}"


# ── enumerating ──────────────────────────────────────────────────

def test_running_lists_live_apps_only():
    rendezvous.publish("rz-test", xsub="tcp://a1", xpub="tcp://b1")
    path = rendezvous.rendezvous_path("rz-stale")
    path.write_text(json.dumps({"app": "rz-stale", "pid": 999_999,
                                "xsub": "tcp://x", "xpub": "tcp://y"}))
    names = {r["app"] for r in rendezvous.running()}
    assert "rz-test" in names
    assert "rz-stale" not in names


# ── it stays local ───────────────────────────────────────────────

def test_the_directory_is_owner_only():
    """This file is enough to publish onto the bus, and the bus carries
    motor commands. The directory mode IS the access control."""
    import stat

    rendezvous.publish("rz-test", xsub="tcp://a", xpub="tcp://b")
    mode = stat.S_IMODE(rendezvous.rendezvous_path("rz-test")
                        .parent.stat().st_mode)
    assert mode & 0o077 == 0, f"world/group readable: {oct(mode)}"


def test_discovery_opens_no_socket():
    """Local only, and it must stay that way. A beacon here would put
    the bus on the network without anyone deciding to.

    Checked against the AST, not the text: the module docstring
    EXPLAINING that there is no multicast contains the word, and a
    substring search cannot tell a promise from a violation. (Third
    time this exact false positive has appeared today.)"""
    import ast

    tree = ast.parse(pathlib.Path(rendezvous.__file__).read_text())

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "socket" not in imported, "rendezvous imports socket"
    assert "socketserver" not in imported

    called = {
        n.func.attr for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    for verb in ("bind", "listen", "sendto", "connect"):
        assert verb not in called, (
            f"rendezvous.py calls {verb}() — cross-machine discovery is "
            f"a separate feature with a different threat model, not "
            f"something to grow into by accident")
