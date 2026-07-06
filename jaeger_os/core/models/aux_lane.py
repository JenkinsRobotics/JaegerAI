"""Aux inference lane — a SECOND llama.cpp context on the ONE loaded model.

Why this exists (measured 2026-07-05, STATUS.md): llama-cpp-python's
``Llama`` object owns exactly one ``llama_context``, and its prefix cache
is single-slot — the KV cache survives only as long as every call shares
the same prompt prefix. The worker lane (agent loop) keeps a ~20K-token
prefix warm; any clean-context side call on the same context (the persona
output filter was the trigger) evicts it, and the next turn pays a full
re-prefill: **ttft 41-44s with the filter ON vs 0.3-0.4s with it OFF**.

llama.cpp itself separates ``llama_model`` (weights, shared) from
``llama_context`` (KV cache + compute state, cheap). llama-cpp-python
0.3.x constructs them as ``internals.LlamaModel`` + ``internals
.LlamaContext(model=...)`` but offers no public "second context on this
model" API. :func:`spawn_aux_context` gets one anyway: it builds a normal
``Llama`` while a scoped constructor patch makes ``internals.LlamaModel``
ADOPT the worker's already-loaded model instead of re-reading the GGUF.
The result is a full-featured ``Llama`` (chat template, grammar, sampling
— everything ``create_chat_completion`` needs) with its OWN small KV
cache, sharing weights byte-for-byte with the worker.

Probe numbers (gemma-4-E4B Q4_K_M, M-series, 2026-07-05):

  * aux construction: 0.08s, +0.13 GB RSS (KV + compute buffers only —
    no second weight load; ``model`` pointer identical)
  * worker warm turn after an aux call: 0.15s (vs 12.8s when the same
    aux call runs through the worker context — the eviction this kills)

Alternative considered — ``Llama.save_state()``/``load_state()`` around
every aux call: measured 0.32s + 0.37s memcpy at 6K tokens (0.14 GB) and
scales linearly (~2s+ and ~0.5 GB per round-trip at 20K), plus the aux
call still cold-prefills inside the borrowed context every time. The
dual context wins on every axis, so save/restore stays unimplemented.

Lifecycle: the aux ``Llama`` must live and die WITH the worker client
that owns the weights (``LlamaCppPythonClient`` stores it as a field).
The adopted-model proxy makes the aux instance's cleanup a no-op on the
shared weights, so whichever object is torn down first can't free the
model out from under the other; the worker's own ExitStack remains the
single owner of the weights' lifetime.
"""

from __future__ import annotations

import threading
from typing import Any

# Serialises the scoped constructor patch in :func:`spawn_aux_context` —
# two threads building Llama instances concurrently must never see each
# other's patch window.
_SPAWN_LOCK = threading.Lock()


class _SharedModelProxy:
    """Stands in for ``internals.LlamaModel`` while adopting an existing
    instance. Forwards every attribute to the worker's model; ``close``
    (and GC) are no-ops so the aux ``Llama``'s ExitStack can never free
    the shared weights — the worker client owns that lifetime."""

    def __init__(self, inner: Any) -> None:
        object.__setattr__(self, "_inner", inner)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_inner"), name)

    def close(self) -> None:  # noqa: D401 — deliberate no-op
        pass

    def __del__(self) -> None:  # pragma: no cover — GC ordering
        pass


def spawn_aux_context(
    worker: Any,
    *,
    n_ctx: int,
    n_batch: int = 512,
    n_ubatch: int = 512,
    flash_attn: bool = True,
) -> Any:
    """Return a new ``Llama`` whose context is fresh but whose model is
    the worker's already-loaded one (no second weight load).

    ``worker`` is the live ``llama_cpp.Llama`` the agent loop decodes on.
    ``n_ctx`` should be small (aux prompts are bounded by design) — every
    token of aux KV is memory the worker's window doesn't get.

    Raises on failure; the caller decides the fallback (JROS falls back
    to sharing the worker context — the pre-0.6.0 behaviour).
    """
    from llama_cpp import Llama
    import llama_cpp.llama as llama_module

    proxy = _SharedModelProxy(worker._model)  # noqa: SLF001 — the point

    def _adopt(**_kwargs: Any) -> Any:
        return proxy

    with _SPAWN_LOCK:
        original = llama_module.internals.LlamaModel
        llama_module.internals.LlamaModel = _adopt  # type: ignore[assignment]
        try:
            aux = Llama(
                model_path=worker.model_path,
                n_ctx=int(n_ctx),
                n_batch=n_batch,
                n_ubatch=n_ubatch,
                flash_attn=flash_attn,
                verbose=False,
            )
        finally:
            llama_module.internals.LlamaModel = original
    return aux


__all__ = ["spawn_aux_context"]
