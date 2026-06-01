"""v1.0.0 → v1.1.0 — first real migration.

Exercises the per-instance migration runner end-to-end so the
mechanism is tested before a real schema change has to ride on it.

The actual 0.2.0 layout move (legacy ``~/.jaeger/<name>/`` →
``~/.jaeger/instances/<name>/``) is handled BEFORE the resolver
fires, in ``core/instance/legacy_migrations.py`` — that has to be
a pre-resolver bootstrap because the layout passed to this
function points at the location where the resolver FOUND the
instance, and a freshly-migrated 0.1.0 user's instance is already
at the new path by the time this code runs.

So this migration is structurally light — its job is to ensure
each migrated instance's ``config.yaml`` carries the new
``interaction`` field (added in WIZ-3) instead of silently
relying on the schema's ``default_factory``. That brings a 0.1.0
on-disk config into 0.2.0-shape explicitly, so the next
``jaeger update`` doesn't have a stale config gnawing at it.
The runner then bumps ``manifest.core_version`` from
``"1.0.0"`` to ``"1.1.0"`` automatically.
"""

from __future__ import annotations

from jaeger_os.core.instance.instance import InstanceLayout
from jaeger_os.core.instance.schemas import (
    Config, InteractionConfig, dump_yaml, load_yaml,
)


def migrate(layout: InstanceLayout) -> None:
    """Apply the v1.0.0 → v1.1.0 changes to ``layout``.

    Idempotent — re-running is harmless.
    """
    # Re-dump config.yaml so the file on disk explicitly carries
    # ``interaction.default_mode: tui``. A 0.1.0 config that
    # implicitly defaulted now becomes explicit.
    try:
        cfg: Config = load_yaml(layout.config_path, Config)
    except Exception:  # noqa: BLE001 — never let a malformed config block migrate
        return
    if cfg.interaction is None:  # type: ignore[unreachable]
        # default_factory should have populated this, but be
        # defensive in case a hand-edit removed the field entirely.
        cfg = cfg.model_copy(update={"interaction": InteractionConfig()})
    dump_yaml(layout.config_path, cfg)
