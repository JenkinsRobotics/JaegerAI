"""{{package_name}} — {{DESCRIPTION}}

Exports the ``module.yaml`` factory entrypoint (``make_{{package_name}}_node``,
rename to match your module.yaml's ``factory:`` field once real) so
JaegerOS's module discovery can import it by dotted path.

Delete this docstring's placeholder language once the module is real.
"""

from __future__ import annotations

__version__ = "0.1.0"

# Uncomment once node.py.example -> node.py and the factory is written:
# from .node import make_{{package_name}}_node, {{PackageName}}Node
#
# __all__ = ["make_{{package_name}}_node", "{{PackageName}}Node", "__version__"]

__all__ = ["__version__"]
