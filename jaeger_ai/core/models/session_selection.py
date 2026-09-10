"""Conversation-scoped external model selection; never writes instance config."""
from __future__ import annotations


def select_client(default, config, layout, model=None, provider=None):
    if not model or model == 'default':
        return default
    from jaeger_ai.core.models.configuration import _BASE_URLS, _CREDENTIALS, _reject_cross_vendor_pair
    from jaeger_ai.core.models.external_model import ExternalModelClient
    from jaeger_ai.core.models.ollama_endpoint import (
        normalize_ollama_provider,
        resolve_ollama_base_url,
    )
    selected = str(model).strip()
    # The WebUI's local/cloud categories are both served by its Ollama daemon.
    provider = normalize_ollama_provider(str(provider or '').strip().lower())
    ext = config.external_model.model_copy(deep=True)
    owner = provider or (ext.provider if ext.enabled else 'local')
    owner = normalize_ollama_provider(owner)
    current = str(getattr(default, 'model_name', '') or '')
    if selected == current and owner == getattr(default, 'provider', owner):
        return default
    if owner not in _BASE_URLS or owner == 'cli':
        raise ValueError('Per-conversation model selection requires a configured external provider; local/CLI model changes use instance settings')
    _reject_cross_vendor_pair(owner, selected)
    if owner != ext.provider:
        if owner == 'ollama':
            ext.base_url = resolve_ollama_base_url()
            ext.api_key_credential = ''
            ext.api_key_env = ''
        else:
            ext.base_url = _BASE_URLS[owner]
            ext.api_key_credential = _CREDENTIALS.get(owner, '')
            ext.api_key_env = ''
    elif owner == 'ollama':
        current_base = str(getattr(ext, 'base_url', '') or '').strip().lower()
        needs_repair = (
            not current_base
            or 'ollama.com' in current_base
            or current_base.startswith('http://127.0.0.1:')
            or current_base.startswith('http://localhost:')
        )
        # Always re-resolve when prior config baked loopback / ollama.com —
        # container guests need 192.168.64.1; Mac host keeps loopback via probe.
        if needs_repair:
            ext.base_url = resolve_ollama_base_url()
            ext.api_key_credential = ''
            ext.api_key_env = ''
    ext.enabled = True
    ext.provider = owner
    ext.model = selected
    return ExternalModelClient(ext, layout)
