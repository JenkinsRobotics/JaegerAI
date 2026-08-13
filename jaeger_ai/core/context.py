"""Compatibility alias — the workspace moved to ``jaeger_agent``.

0.11: this file WAS the agent's sandbox (path resolution, the read/write
gates, the audit trail, git autocommit). It lived under ``core/``
because that is where it grew, but every caller was a tool — so it moved
with them, to :mod:`jaeger_agent.workspace`.

``bind()`` is still called by JaegerAI's boot to point the module's
workspace at the active instance layout. That call IS the seam: the
module owns the sandbox RULES, the application says WHERE.

This module REPLACES ITSELF with the real one rather than re-exporting
from it. A re-export would leave two module objects with two copies of
``_layout``, so binding one would not be visible through the other —
and the sandbox root silently disagreeing with itself is the worst
possible failure in a file-writing tool.
"""

import sys

from jaeger_agent import workspace as _workspace

sys.modules[__name__] = _workspace
