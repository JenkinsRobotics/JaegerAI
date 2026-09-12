"""The migration runner must be able to find its own scripts.

Why this file exists: the 0.9 package split moved the runner to
``jaeger_ai.core.instance.migrations`` while the ``migrations/`` directory
it scans stayed behind in ``jaeger_os``. ``discover_migrations()`` guards
with ``if not MIGRATIONS_DIR.exists(): return []``, so the breakage was
SILENT — the runner is called from six places (boot, ``agent`` verbs,
``update``) and every one of them cheerfully applied zero migrations.

A schema change shipped in that state would have skipped every operator's
instance without a single log line. These tests pin the wiring itself, not
any particular migration, so the directory and the runner cannot drift
apart again.
"""

from __future__ import annotations

import jaeger_ai.core.instance.migrations as migrations_mod
from jaeger_ai.core.instance.migrations import MIGRATIONS_DIR, discover_migrations


def test_migrations_dir_exists():
    """The path the runner scans must be a real directory.

    If this fails, every migration in the repo is being silently ignored.
    """
    assert MIGRATIONS_DIR.is_dir(), (
        f"the migration runner scans {MIGRATIONS_DIR}, which does not exist — "
        "migrations are being silently skipped. Either create that directory "
        "or point MIGRATIONS_DIR at the one holding the scripts."
    )


def test_migrations_dir_is_an_importable_package():
    """Scripts are loaded as modules, so the directory needs ``__init__.py``."""
    assert (MIGRATIONS_DIR / "__init__.py").is_file()


def test_migrations_dir_ships_with_the_runner():
    """The directory must sit inside the package that owns the runner.

    Migrations rewrite ``jaeger_ai`` instance files against ``jaeger_ai``'s
    SCHEMA_VERSION, so both halves belong to the same distribution — split
    across packages, a partial install silently disables the runner again.
    """
    runner_pkg = migrations_mod.__file__.split("/jaeger_ai/")[0] + "/jaeger_ai"
    assert str(MIGRATIONS_DIR).startswith(runner_pkg), (
        f"{MIGRATIONS_DIR} is outside {runner_pkg} — the runner and its "
        "scripts must ship together."
    )


def test_discover_migrations_reads_the_real_directory():
    """Discovery must run without raising and return well-formed entries.

    An empty list is correct today (the 0.5.0 reset cleared the chain); this
    pins the SHAPE so a malformed filename is caught when one is first added.
    """
    found = discover_migrations()
    assert isinstance(found, list)
    for entry in found:
        assert {"name", "from_ver", "to_ver", "from_str", "to_str", "path"} <= set(entry), entry
        assert entry["path"].parent == MIGRATIONS_DIR
        assert isinstance(entry["from_ver"], tuple) and isinstance(entry["to_ver"], tuple)
