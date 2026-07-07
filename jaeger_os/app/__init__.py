"""The Jaeger app-format reference chassis.

This directory IS the thing you copy (docs/JAEGER_APP_FORMAT.md §1):
every Jenkins Robotics app carries its own copy of these modules in
its own repo and owns it outright — the Microsoft-Office model, one
design system, many independent codebases. Nothing imports this
across repositories.

Copy-ability rules (enforced by tests/test_app_format.py):
  * every copy carries the FRAMEWORK_FORMAT stamp below; an app's
    jaeger.toml declares ``requires_framework`` against it.
  * modules import only the stdlib, pyyaml, and each other —
    RELATIVELY — with TWO exceptions, both shared with the real
    nodes instead of a chassis-local duplicate: the bus
    (``jaeger_os.transport``, since 0.8 U1) and Node/NodeState/
    FrameNode (``jaeger_os.nodes.base``, since 0.8 U2 — the chassis's
    ``node.py`` was a strict subset of the real Node and was deleted).

Layout:
  app.py         the chassis — manifest → config → bus → nodes →
                 surfaces → run → teardown
  supervisor.py  NodeHandle + thread/subprocess backends, restart
                 policy (never|on_failure|always + backoff), diagnose
  manifest.py    jaeger.toml loader + validator
  config.py      config.yaml loader (refuse loudly)
  surfaces.py    Surface contract + SurfaceManager + bus→Qt bridge
  health.py      NodeHealth heartbeats + the liveness cache
  logging.py     one log-line shape + the /sys/log bus mirror

The bus is ``jaeger_os.transport`` (0.8 U1 deleted the duplicate
``app/bus/`` and the chassis-ZMQ path it carried — unexercised, since
both shipped manifests run ``[bus] backend = "inproc"``; transport's
ZMQ is the canon for any later cross-process work). The
subprocess-node ZMQ bootstrap helper (``child.py``) went with it —
no manifest in this repo ever configured a subprocess node, so it
was dead weight once the bus it bootstrapped was gone.
"""

from __future__ import annotations

from jaeger_os.transport import Bus, InProcBus

from .app import JaegerApp
from .config import load_config
from .core import Core, CoreMainThreadError
from .health import HealthCache
from .logging import LogLine, log
from .manifest import (
    AppSpec, BusSpec, CoreSpec, NodeSpec, SurfaceSpec, load_manifest,
)
from jaeger_os.nodes.base import FrameNode, Node, NodeState
from .supervisor import NodeHandle, Supervisor

# The copy's format stamp — what jaeger.toml's `requires_framework`
# checks against (manifest.py reads it lazily; no import cycle).
FRAMEWORK_FORMAT = "0.1"

__all__ = [
    "FRAMEWORK_FORMAT",
    "JaegerApp",
    "Node", "FrameNode", "NodeState",
    "Core", "CoreMainThreadError",
    "Supervisor", "NodeHandle",
    "Bus", "InProcBus",
    "AppSpec", "NodeSpec", "SurfaceSpec", "BusSpec", "CoreSpec",
    "load_manifest",
    "load_config",
    "HealthCache",
    "LogLine", "log",
]
