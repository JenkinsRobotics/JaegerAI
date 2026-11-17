"""The web app modules import each other as ``api.<name>``; importing the
package installs that alias (see jaeger_ai/core/gateway/webapp/__init__.py)."""
from __future__ import annotations

import jaeger_ai.core.gateway.webapp  # noqa: F401
