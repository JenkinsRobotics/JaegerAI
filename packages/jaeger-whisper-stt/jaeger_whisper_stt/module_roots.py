"""Entry-point target for ``jaeger_os.core.modules``'s ``discover_modules()``
out-of-tree seam (0.9 step 4 split).

This repo ships one module (``nodes/whisper_stt/``) in its own
installed package. Registered under the ``jaeger_os.module_roots``
entry-point group (see this repo's ``pyproject.toml``) so JaegerOS's
``discover_modules()`` finds it WITHOUT ever importing or naming
``jaeger_whisper_stt`` — the framework only knows the group name, never
the contributor.
"""

import pathlib

_HERE = pathlib.Path(__file__).resolve().parent


def roots() -> tuple[pathlib.Path, ...]:
    return (_HERE / "nodes",)
