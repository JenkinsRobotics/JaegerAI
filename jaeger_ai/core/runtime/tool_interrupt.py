"""Compatibility alias — tool interruption moved to ``jaeger_agent``.

0.11: pure stdlib (threading events + interruptible subprocess), used
only by tools and coupled to nothing JaegerAI-specific, so it moved with
them to :mod:`jaeger_agent.util.tool_interrupt`.

Replaces itself with the real module for the same reason
``core/context.py`` does: the interrupt flag is module-level state, and
two copies of it means a cancel that reaches one and not the other.
"""

import sys

from jaeger_agent.util import tool_interrupt as _tool_interrupt

sys.modules[__name__] = _tool_interrupt
