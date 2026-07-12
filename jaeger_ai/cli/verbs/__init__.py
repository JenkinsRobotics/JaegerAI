"""In-process ``jaeger <verb>`` CLI commands.

These verbs (bench, setup, instance, migrate, backup, restore, update,
skill, memory, kill, health) do their work in the calling process. They
lived under ``jaeger_os/daemon/`` while a multi-process daemon split was
planned; that architecture was dropped on 2026-06-14 (JROS converged on
fused mode), the daemon-process machinery was deleted, and the verbs moved
here. :mod:`jaeger_os.cli.verbs.dispatch` routes ``sys.argv`` to them.
"""

from __future__ import annotations
