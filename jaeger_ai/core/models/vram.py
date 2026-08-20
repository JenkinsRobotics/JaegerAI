"""Explicit release of a LOCAL model's weights — and the GPU memory
they hold — instead of waiting for the garbage collector.

Why this exists: on a unified-memory Mac the weights are VRAM. Dropping
the last Python reference to a ``LlamaCppPythonClient`` / ``MlxClient``
does free them eventually, but "eventually" is whenever CPython's cycle
collector gets around to the object graph — the client, its aux-lane
``Llama``, its executor thread, and (for MLX) the framework's own buffer
cache all sit between the reference drop and the memory actually coming
back. Switching a 15.7 GB local model out for a cloud model and finding
15 GB still resident is the failure this module removes: the release is
now a step the switch performs, not a side effect it hopes for.

Two things need doing that a plain ``del`` does not:

  * **llama.cpp** frees its Metal buffers in ``Llama.close()`` (an
    ``ExitStack``), which ``__del__`` only reaches once the object is
    collected. The AUX LANE (see :mod:`.aux_lane`) holds a second
    ``Llama`` on the same weights — closing it first releases its KV
    cache, and its ``_SharedModelProxy`` makes that close a no-op on the
    shared weights, so ordering is safe either way.
  * **MLX** returns freed arrays to its own buffer cache rather than to
    the OS; ``mx.clear_cache()`` is what actually hands the memory back.
    MLX also pins a GPU stream to the thread that created it, so the
    clear runs on the client's own single-thread executor when that
    executor is still alive.

Everything here is best-effort by design: a client that fails to close
cleanly must never take the switch down with it — the worst case is the
memory comes back at GC time, which is where we started.
"""

from __future__ import annotations

import gc
from typing import Any


def _close_quietly(obj: Any, attr: str = "close") -> None:
    """Call ``obj.<attr>()`` if it exists, swallowing any failure."""
    if obj is None:
        return
    fn = getattr(obj, attr, None)
    if not callable(fn):
        return
    try:
        fn()
    except Exception:  # noqa: BLE001 — teardown is best-effort
        pass


def _clear_mlx_cache(executor: Any = None) -> None:
    """Hand MLX's buffer cache back to the OS.

    ``mx.clear_cache()`` is the modern spelling; older mlx wheels expose
    it as ``mx.metal.clear_cache()``. Runs on ``executor`` when one is
    given and still accepting work, because MLX binds its GPU stream to
    the thread that created it.
    """
    try:
        import mlx.core as mx  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 — not an MLX host / wheel absent
        return

    clear = getattr(mx, "clear_cache", None)
    if not callable(clear):
        clear = getattr(getattr(mx, "metal", None), "clear_cache", None)
    if not callable(clear):
        return

    if executor is not None:
        try:
            executor.submit(clear).result(timeout=10)
            return
        except Exception:  # noqa: BLE001 — executor already down / shut
            pass
    try:
        clear()
    except Exception:  # noqa: BLE001
        pass


def release_local_client(client: Any) -> bool:
    """Free the weights held by ``client`` and return whether it held any.

    Returns ``True`` when a LOCAL client was released, ``False`` for
    ``None`` or for an external client (which holds no local weights —
    there is nothing to unload when the brain is an HTTP endpoint).

    The client is left inert: its model handles are nulled, so a stray
    reference that survives the switch raises an ``AttributeError``
    instead of decoding into freed weights.

    Callers still have to drop their OWN reference — this function can
    reach ``_pipeline`` and the object's fields, never a local variable
    in the caller's frame.
    """
    if client is None:
        return False
    if str(getattr(client, "kind", "local") or "local") != "local":
        return False

    executor = getattr(client, "_executor", None)

    # 1. llama.cpp — aux lane first (its KV cache), then the worker's
    #    weights. Both are no-ops on a client that never built one.
    _close_quietly(getattr(client, "_aux_llm", None))
    _close_quietly(getattr(client, "llm", None))

    # 2. Drop every handle we know about so the refcount actually hits
    #    zero. MLX arrays are refcounted, so this is what returns their
    #    buffers to the framework cache that step 3 then clears.
    was_mlx = False
    for attr in ("_aux_llm", "llm", "_mlx_model", "_tokenizer", "_processor"):
        if getattr(client, attr, None) is not None:
            was_mlx = was_mlx or attr == "_mlx_model"
            try:
                setattr(client, attr, None)
            except Exception:  # noqa: BLE001 — frozen / slotted client
                pass

    # 3. MLX's cache holds the freed buffers until told otherwise.
    if was_mlx:
        _clear_mlx_cache(executor)

    # 4. The generation thread outlives the weights otherwise. Don't wait
    #    on it: a hung decode must not block the switch.
    if executor is not None:
        try:
            executor.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass
        try:
            client._executor = None  # noqa: SLF001 — teardown
        except Exception:  # noqa: BLE001
            pass

    gc.collect()
    return True


__all__ = ["release_local_client"]
