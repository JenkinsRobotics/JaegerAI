"""Entry-point target for ``jaeger_os.core.modules``'s ``discover_modules()``
out-of-tree seam (0.9 step 4 split).

Registered under the ``jaeger_os.module_roots`` entry-point group (see
this repo's ``pyproject.toml``) so JaegerOS's ``discover_modules()``
finds this module WITHOUT ever importing or naming
``jaeger_whisper_stt`` — the framework only knows the group name, never
the contributor.

The root IS the module: ``module.yaml`` sits directly in this package,
so ``discover_modules()`` takes its "root that is itself a module"
branch rather than scanning for module subdirectories. That is the
singleton shape — one repo, one module — and it is why this returns the
package directory instead of a ``nodes/`` subdirectory holding a single
child. A repo shipping SEVERAL modules would return the directory that
holds them.
"""

import pathlib

_HERE = pathlib.Path(__file__).resolve().parent


def roots() -> tuple[pathlib.Path, ...]:
    return (_HERE,)
