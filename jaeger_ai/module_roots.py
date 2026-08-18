"""Entry-point target for ``jaeger_os.core.modules``'s ``discover_modules()``
out-of-tree seam (0.9 step 4 split).

JaegerAI's default discovery roots (``NODES_DIR``/``PLUGINS_DIR``/
``AGENT_DIR``) only ever see ITS OWN tree — post-split, JaegerAI's
``nodes/`` (animation/animation_dev/media), ``plugins/`` (messaging
channels, MCP, ai_gen, home assistant), and the product's ``mind/`` binding
live in this installed package. ``jaeger-agent`` supplies the reusable loop;
JaegerAI supplies the product-owned mind binding and instance state.
These roots are registered under the
``jaeger_os.module_roots`` entry-point group (see this repo's
``pyproject.toml``) so ``discover_modules()`` finds them WITHOUT
JaegerAI ever importing or naming ``jaeger_ai`` — the framework only
knows the group name, never the contributor.
"""

import pathlib

_HERE = pathlib.Path(__file__).resolve().parent


def roots() -> tuple[pathlib.Path, ...]:
    return (_HERE / "nodes", _HERE / "plugins", _HERE / "mind")
