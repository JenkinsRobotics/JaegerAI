"""How a picker-qualified model id encodes the provider lane that served it.

Model discovery and the WebUI picker mint ids of the form::

    @ollama-cloud:glm-5.3-flash:cloud     lane "ollama-cloud", model "glm-5.3-flash:cloud"
    @ollama-local:qwen3:8b                lane "ollama-local", model "qwen3:8b"

The ``@lane:`` prefix is a routing hint for the picker. It is not part of the
name any provider accepts: sent verbatim to Ollama's OpenAI-compatible endpoint
it is rejected with ``400 invalid model name``. That is exactly what happened
when a picker id was persisted into ``external_model.model`` — every tool-using
turn failed while the text-only lane, which stripped the hint itself, kept
working and hid the breakage.

The lane is the text between ``@`` and the first colon; everything after it is
the provider's model name, colons included (Ollama tags such as ``:cloud``).
"""
from __future__ import annotations


def split_routed_model_id(model_id: str) -> tuple[str | None, str]:
    """Return ``(lane, model)`` for ``@lane:model``, or ``(None, model_id)``."""
    value = str(model_id or "").strip()
    if value.startswith("@") and ":" in value:
        lane, model = value[1:].split(":", 1)
        return lane, model
    return None, value


def provider_model_name(model_id: str) -> str:
    """The model name a provider accepts, with any ``@lane:`` hint removed."""
    return split_routed_model_id(model_id)[1]
