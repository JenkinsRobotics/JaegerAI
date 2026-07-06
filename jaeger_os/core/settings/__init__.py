"""Schema-derived settings catalog — the ONE source every surface reads.

Settings are defined exactly once, as ``Field(...)`` on the Pydantic
schemas (``core/instance/schemas.py``). :mod:`jaeger_os.core.settings.catalog`
walks those schemas and emits a typed descriptor per exposed leaf field;
the CLI (``jaeger settings``) and the Swift app both render + mutate through
that single catalog. There is deliberately NO hand-enumerated settings list
in Swift and NO parallel field map in the bridge — a new setting is one
annotated field here and it appears everywhere. It is a plain module over the
``Config`` schema, not a provider/plugin framework (that federation seam is a
0.8 concern — see ``dev/docs/framework_vision.md``).

Import the API from the submodule to keep the ``catalog`` function distinct
from the ``catalog`` module::

    from jaeger_os.core.settings.catalog import catalog, set_value, get_value
"""

from __future__ import annotations
