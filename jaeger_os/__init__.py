"""JaegerOS — the framework layer of the Jaeger ecosystem.

Bus, Node, the module/slot system, the supervisor, the safety floor,
the wire contract, and the hardware capability layer. Libraries +
standards + tooling, the way ROS is to a robot stack — projects and
modules BUILD ON this, pinned to a release; nothing here imports the
Mind (see ``dev/tests/jaeger_os/core/test_layering.py``).

Split out of the JROS monorepo in the 0.9 four-way split (staged
dev/docs/roadmap/SPLIT_FILE_MAP.md in the JROS repo); history preserved
via ``git filter-repo``.
"""

__version__ = "0.9.0"
