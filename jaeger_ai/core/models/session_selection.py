"""Conversation-scoped external model selection; never writes instance config."""
from __future__ import annotations


def select_client(default, config, layout, model=None, provider=None):
    if not model or model == 'default':
        return default
    from jaeger_ai.core.models.configuration import _BASE_URLS, _CREDENTIALS, _reject_cross_vendor_pair
    from jaeger_ai.core.models.external_model import ExternalModelClient
    selected = str(model).strip()
    # The WebUI's local/cloud categories are both served by its Ollama daemon.
    provider = str(provider or '').strip().lower()
    if provider in {'ollama-local', 'ollama-cloud'}:
        provider = 'ollama'
    ext = config.external_model.model_copy(deep=True)
    owner = provider or (ext.provider if ext.enabled else 'local')
    current = str(getattr(default, 'model_name', '') or '')
    if selected == current and owner == getattr(default, 'provider', owner):
        return default
    if owner not in _BASE_URLS or owner == 'cli':
        raise ValueError('Per-conversation model selection requires a configured external provider; local/CLI model changes use instance settings')
    _reject_cross_vendor_pair(owner, selected)
    if owner != ext.provider:
        ext.base_url = _BASE_URLS[owner]
        ext.api_key_credential = _CREDENTIALS.get(owner, '')
        ext.api_key_env = ''
    ext.enabled = True
    ext.provider = owner
    ext.model = selected
    return ExternalModelClient(ext, layout)
