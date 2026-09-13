"""Keep first-run provider keys until their instance credential store exists."""
from __future__ import annotations

import os
from typing import Any

_pending: dict[str, str] = {}


def calibrate_provider(layout: Any, provider: Any, api_key: Any) -> None:
    from jaeger_ai.core.models.external_model import _CONVENTIONAL_ENV, _PROVIDER_CREDENTIAL_ALIASES
    from jaeger_ai.core.credential_service import set_credential
    provider = str(provider or "").strip().lower()
    key = str(api_key or "").strip()
    if provider not in _PROVIDER_CREDENTIAL_ALIASES:
        raise ValueError("Unsupported credential provider")
    if not key:
        raise ValueError("API key cannot be empty")
    # Store only the provider-specific name; the shared external_model alias
    # would let one vendor's key overwrite another vendor's credentials.
    name = _PROVIDER_CREDENTIAL_ALIASES[provider][0]
    if layout is None:
        _pending[name] = key
    else:
        set_credential(layout, name, key)
    for variable in _CONVENTIONAL_ENV.get(provider, ()):
        os.environ[variable] = key


def persist_pending(layout: Any) -> None:
    from jaeger_ai.core.credential_service import set_credential
    for name, key in list(_pending.items()):
        set_credential(layout, name, key)
        del _pending[name]
