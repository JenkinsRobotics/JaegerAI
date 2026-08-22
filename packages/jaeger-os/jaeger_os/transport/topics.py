"""topics.py — re-export shim.

The topic names + msgspec schemas moved to :mod:`jaeger_os.contract.topics`
in the 0.9 contract package (the one wire truth — see
``dev/docs/vision/THREE_TIER_STRUCTURE.md``). This module re-exports the
contract unchanged so the ~60 existing ``from jaeger_os.transport import
topics`` / ``topics.SOME_CONSTANT`` call sites across nodes, plugins, agent,
interfaces, and tests keep working without a repoint — churn too large to
justify for a pure rename. New code should import
:mod:`jaeger_os.contract.topics` directly; this shim is not the source of
truth.

Uses a full attribute mirror rather than ``import *`` because the historical
``__all__`` here predates several topic families (animation, timeline,
media, skill-tree) and was never backfilled — plain attribute access
(``topics.ACT_ANIMATION``) must keep working for all of them.
"""

from __future__ import annotations

from jaeger_os.contract import topics as _contract_topics

globals().update({
    _name: getattr(_contract_topics, _name)
    for _name in dir(_contract_topics)
    if not _name.startswith("_")
})

__all__ = _contract_topics.__all__
