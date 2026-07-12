"""The aux inference lane — ``LlamaCppPythonClient.chat`` is THE
chokepoint for every bounded side-channel call (persona filter,
skip-final finalizer, reflection, deep-think planning, memory review).

Contract under test: chat() decodes on the AUX context (a second
llama_context on the same loaded model) so it can never evict the
worker context's warm KV prefix — the measured 40s-per-turn persona
regression. Fallbacks: spawn failure or ``aux_ctx: 0`` degrade to the
worker context (pre-0.6.0 behaviour), never to a crashed turn.
"""

from __future__ import annotations

import threading

import jaeger_ai.core.models.aux_lane as aux_lane_mod
from jaeger_ai.main import LlamaCppPythonClient


class _StubLlama:
    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.calls: list[dict] = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return {"choices": [{"message": {"content": f"from-{self.tag}"}}]}


def _bare_client(aux_ctx: int = 4096) -> LlamaCppPythonClient:
    """A client skeleton with the aux-lane fields but no model load."""
    c = object.__new__(LlamaCppPythonClient)
    c.llm = _StubLlama("worker")
    c._aux_kwargs = {"n_ctx": aux_ctx, "n_batch": 512, "n_ubatch": 512,
                     "flash_attn": True}
    c._aux_llm = None
    c._aux_lock = threading.Lock()
    return c


def test_chat_routes_to_aux_context_not_worker(monkeypatch):
    spawned: list[dict] = []

    def _spawn(worker, **kwargs):
        spawned.append(kwargs)
        return _StubLlama("aux")

    monkeypatch.setattr(aux_lane_mod, "spawn_aux_context", _spawn)
    client = _bare_client(aux_ctx=2048)

    out = client.chat([{"role": "user", "content": "restyle this"}],
                      max_tokens=64)
    assert out.text == "from-aux"
    assert client.llm.calls == []            # worker KV never touched
    assert spawned == [{"n_ctx": 2048, "n_batch": 512, "n_ubatch": 512,
                        "flash_attn": True}]

    # Second call reuses the spawned lane — one context per client life.
    client.chat([{"role": "user", "content": "again"}])
    assert len(spawned) == 1
    assert len(client._aux_llm.calls) == 2


def test_spawn_failure_falls_back_to_worker_once(monkeypatch, capsys):
    attempts = {"n": 0}

    def _boom(worker, **kwargs):
        attempts["n"] += 1
        raise RuntimeError("no second context on this build")

    monkeypatch.setattr(aux_lane_mod, "spawn_aux_context", _boom)
    client = _bare_client()

    out = client.chat([{"role": "user", "content": "hi"}])
    assert out.text == "from-worker"         # degraded, not crashed
    assert "aux lane unavailable" in capsys.readouterr().out

    # The failure latches (aux_ctx -> 0): no per-call retry storm.
    client.chat([{"role": "user", "content": "hi again"}])
    assert attempts["n"] == 1
    assert len(client.llm.calls) == 2


def test_aux_ctx_zero_disables_the_lane(monkeypatch):
    def _never(worker, **kwargs):
        raise AssertionError("lane disabled — spawn must not run")

    monkeypatch.setattr(aux_lane_mod, "spawn_aux_context", _never)
    client = _bare_client(aux_ctx=0)
    out = client.chat([{"role": "user", "content": "hi"}])
    assert out.text == "from-worker"


def test_model_config_default_and_disable():
    from jaeger_ai.core.instance.schemas import ModelConfig
    cfg = ModelConfig(model_path="/dev/null")
    assert cfg.aux_ctx == 4096               # operator-required default
    assert ModelConfig(model_path="/dev/null", aux_ctx=0).aux_ctx == 0
