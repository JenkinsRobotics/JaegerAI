"""Windowed-app entry — what a bare ``./launch`` runs (Pattern 1).

Boots JROS's PySide6 chat window + menu-bar tray through the chassis
``JaegerApp`` with a Tier-1 ``[core]``. All the substance — the model
boot, the bus bridge, teardown order — lives in the core
(``jaeger_os.agent.loop.agent_core:AgentCore``) and the surfaces. This
module only points the chassis at ``jaeger.windowed.toml`` and runs it,
so there is ONE app/host (the chassis), no second ``JaegerApp`` class.

The instance is resolved by ``boot_for_tui`` from ``JAEGER_INSTANCE_NAME``
(launch.py sets it in the sandbox env), so no ``--instance`` plumbing.
"""

from __future__ import annotations

import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_MANIFEST = _REPO_ROOT / "jaeger.windowed.toml"


def main() -> int:
    from jaeger_os.app import JaegerApp

    return JaegerApp(_MANIFEST).run()


if __name__ == "__main__":
    raise SystemExit(main())
