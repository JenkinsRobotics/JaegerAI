"""A message typed during a runner-owned run is queued, not bounced.

Live regression (WebUI, 2026-09-22): the second message of a Jaeger
conversation, sent while the first turn was still finishing, went to
/api/chat/steer, got ``no_cached_agent``, and was pushed back into the
composer instead of being sent after the run.
"""

from __future__ import annotations

from types import SimpleNamespace

